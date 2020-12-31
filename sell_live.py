import pandas as pd
import statistics
from datetime import datetime, timedelta
from pytz import timezone


class LiveSeller:

    def __init__(self, ratings_df, market_close_dt, api):
        self.api = api
        self.ratings_df = ratings_df
        self.market_close_dt = market_close_dt
        self.still_selling = True

    def run(self):
        pass
