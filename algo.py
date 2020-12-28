import alpaca_trade_api as tradeapi
import pandas as pd
import statistics
import time
import config
import requests
from ta.volume import ChaikinMoneyFlowIndicator as cmfi
from datetime import datetime, timedelta
from pytz import timezone

api = tradeapi.REST(config.KEY_ID, config.SECRET_KEY, config.URL)

stock_divisor = 15
max_stock_price = 13
min_stock_price = 2
min_prcnt_chng = 0.035
max_batch_size = 200
time_window = 5
max_rating_fraction = 0.25


def get_all_ratings(max_stocks):
    print('Filtering assets and calculating ratings...')
    assets = api.list_assets()
    assets = [asset for asset in assets if asset.tradable]
    ratings = pd.DataFrame(columns=['symbol', 'rating', 'price'])
    index = 0
    while index < len(assets):
        symbol_batch = [
            asset.symbol for asset in assets[index:index+max_batch_size]
        ]
        bar_data = api.get_barset(
            symbols=symbol_batch,
            timeframe='day',
            limit=time_window
        )
        for symbol in symbol_batch:
            bars = bar_data[symbol]
            if len(bars) == time_window:
                latest_time = bars[-1].t.to_pydatetime().astimezone(timezone('EST'))
                latest_price = bars[-1].c
                day_prcnt_chng = bars[-1].c/bars[-2].c - 1
                if (
                    latest_price <= max_stock_price and
                    latest_price >= min_stock_price and
                    day_prcnt_chng >= min_prcnt_chng
                ):

                    price_change = latest_price - bars[0].c
                    past_volumes = [bar.v for bar in bars[:-1]]
                    volume_stdev = statistics.stdev(past_volumes)
                    if volume_stdev == 0:
                        continue
                    volume_change = bars[-1].v - bars[-2].v
                    rating = (volume_change / volume_stdev) * \
                        (price_change / bars[0].c)
                    if rating > 0:
                        ratings = ratings.append({
                            'symbol': symbol,
                            'rating': rating,
                            'price': latest_price
                        }, ignore_index=True)
        index += max_batch_size
    ratings = ratings.sort_values('rating', ascending=False)
    ratings = ratings.reset_index(drop=True)
    ratings = ratings[:int(max_stocks)]
    print('Found {} stocks, with total rating: {}'.format(
        ratings.shape[0], ratings['rating'].sum()))
    trim_outlier_ratings(ratings_df=ratings)
    return ratings


def trim_outlier_ratings(ratings_df):
    total_rating = ratings_df['rating'].sum()
    trimmed_ratings = pd.DataFrame(columns=['symbol', 'rating', 'price'])
    max_rating = ratings_df['rating'].max()
    new_max_rating = total_rating * max_rating_fraction
    if max_rating > total_rating * 0.5:
        print('Outlier found! Trimming...')
        ratings_df.loc[ratings_df['rating'] ==
                       max_rating, 'rating'] = new_max_rating
        points_to_add = (max_rating - new_max_rating) / ratings_df.shape[0]
        print('Distributing {} points to each stock'.format(points_to_add))
        for i, row in ratings_df.iterrows():
            if row['rating'] != new_max_rating:
                ratings_df.loc[ratings_df['rating'] ==
                               row['rating'], 'rating'] += points_to_add
        print('New total rating: {}'.format(ratings_df['rating'].sum()))
    else:
        print('No outliers found!')


def get_shares_to_buy(ratings_df, portfolio):
    print('Calculating shares to buy...')
    total_rating = ratings_df['rating'].sum()
    shares = {}
    for _, row in ratings_df.iterrows():
        num_shares = int(row['rating'] / total_rating *
                         portfolio / row['price'])
        if num_shares == 0:
            continue
        shares[row['symbol']] = num_shares
    return shares


def run():
    tick_count = 0
    bought_today = False
    sold_today = False

    try:
        orders = api.list_orders(
            after=pd.Timestamp(datetime.today()-timedelta(days=1)).date(),
            limit=max_stocks*2,
            status='all'
        )
        for order in orders:
            if order.side == 'buy' and order.status != 'canceled':
                bought_today = True
                sold_today = True
                break
            else:
                sold_today = True
    except:
        pass

    while True:
        clock = api.get_clock()
        max_stocks = float(api.get_account().cash) // stock_divisor
        if clock.is_open and not bought_today:
            if sold_today:
                time_until_close = clock.next_close - clock.timestamp
                print('Waiting to buy...')
                if time_until_close.seconds <= 120:
                    print('Buying positions...')
                    portfolio_cash = float(api.get_account().cash)
                    ratings = get_all_ratings(max_stocks)
                    shares_to_buy = get_shares_to_buy(ratings, portfolio_cash)
                    for symbol in shares_to_buy:
                        api.submit_order(
                            symbol=symbol,
                            qty=shares_to_buy[symbol],
                            side='buy',
                            type='market',
                            time_in_force='day'
                        )
                    print('Positions bought.')
                    bought_today = True
            else:
                time_after_open = clock.next_open - clock.timestamp
                print('Waiting to sell...')
                if time_after_open.seconds >= 60:
                    print('Liquidating positions.')
                    api.close_all_positions()
                sold_today = True
        else:
            bought_today = False
            sold_today = False
            if tick_count % 5 == 0:
                print("Waiting for market open ...\n(now: {}, next open: {})".format(
                    clock.timestamp.round('1s'), clock.next_open))
        time.sleep(3)
        tick_count += 1


def log_shares(shares, ratings):
    total_price = 0
    for share in shares:
        price = ratings.loc[ratings['symbol'] == share, 'price'].values[0]
        print('{} stocks of {} posed to be bought at ${} for ${}'.format(
            shares[share],
            share,
            round(price, 2),
            round(price*shares[share], 2)
        ))
        total_price += price*shares[share]
    print('${} to be spent from ${}'.format(
        round(total_price, 2), int(api.get_account().cash)))


if __name__ == '__main__':
    ratings = get_all_ratings(float(api.get_account().cash) // stock_divisor)
    shares = get_shares_to_buy(ratings, float(api.get_account().cash))
    log_shares(shares, ratings)

# uncomment to use sentiment
# try:
#     res = requests.get(
#         config.FINNHUB_URL+'news-sentiment',
#         params={'symbol': symbol},
#         headers={'X-Finnhub-Token': config.FINNHUB_KEY}
#     ).json()
#     if res['sentiment'] is not None and res['sentiment']['bullishPercent'] < 0.5:
#         continue
# except:
#     pass
