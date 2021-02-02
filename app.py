import argparse
import json
import logging
import os
import smtplib
import ssl
import string
import subprocess

import spacy
import tweepy
from databay import Inlet, Link
from databay.outlet import Outlet
from databay.planners import SchedulePlanner
from databay.record import Record

logging.basicConfig(
    format="%(asctime)s : %(levelname)s : %(message)s", level=logging.INFO
)

PUNCTUATION = "!\"#$%&'()*+,./:;<=>?@[\\]^_`{|}~"
SIMILARITY_THRESHOLD = 0.80


class TwitterInlet(Inlet):
    """
    An implementation of an `Inlet` that uses the Tweepy (https://www.tweepy.org/)
    Twitter client to pull tweets from either a specific users' timeline or the
    home timeline belonging to an authenticated `tweepy.API` instance.
    """

    def __init__(
        self, api: tweepy.API, user: str = None, most_recent_id=None, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.api = api
        self.user = user

        # this will ensure we only every pull tweets that haven't been handled
        self.most_recent_id = most_recent_id

        # sets flag indicating whether we are pulling from as single user
        # or from the home timeline.
        if self.user is None:
            self.is_user_timeline = False
        else:
            self.is_user_timeline = True

    def pull(self, update):
        if self.is_user_timeline:
            if self.most_recent_id is not None:
                public_tweets = self.api.user_timeline(
                    self.user, since_id=self.most_recent_id
                )
            else:
                public_tweets = self.api.user_timeline(self.user)
        else:
            if self.most_recent_id is not None:
                public_tweets = self.api.home_timeline(since_id=self.most_recent_id)
            else:
                public_tweets = self.api.home_timeline()

        if len(public_tweets) > 0:
            # 0th tweet is most recent
            self.most_recent_id = public_tweets[0].id

        tweets = []
        for tweet in public_tweets:
            tweets.append({"user": tweet.user.screen_name, "text": tweet.text})
        return tweets


class SMTPStockEmailOutlet(Outlet):
    def __init__(
        self,
        email_address: str,
        password: str,
        receiver_addresses: list[str],
        stock_datapath: str,
    ):
        super().__init__()
        self.port = 465
        self.email_address = email_address
        self.password = password
        self.receiver_addresses = receiver_addresses
        self.stock_data = self._load_data(stock_datapath)
        self.symbols = self._get_symbols(self.stock_data)
        self.proper_stock_names = self._get_stock_proper_name(self.stock_data)

        context = ssl.create_default_context()
        self.server = smtplib.SMTP_SSL("smtp.gmail.com", self.port, context=context)
        self.server.login(self.email_address, self.password)

        try:
            # make sure to use larger package!
            self.nlp = spacy.load("en_core_web_lg")

        except Exception:
            subprocess.call("python -m spacy download en_core_web_lg", shell=True)
            # make sure to use larger package!
            self.nlp = spacy.load("en_core_web_lg")

        logging.info("Initialized Spacy Language Model")

        # self.server.sendmail(self.email_address, receiver_email, message)

    def push(self, records: list[Record], update):
        for record in records:
            print()

    def on_shutdown(self):
        self.server.close()

    def _analyze_tweet(self, tweet: str):
        tweet = tweet.translate(str.maketrans("", "", string.punctuation))
        stopwords = self.nlp.Defaults.stop_words
        mentions = []
        tweet_tokens = tweet.split(" ")
        tweet_tokens = [word for word in tweet_tokens if word not in stopwords]
        for token in tweet_tokens:
            for symbol in self.symbols:
                doc1 = self.nlp(symbol)
                doc2 = self.nlp(token)
                similarity = doc1.similarity(doc2)
                if similarity >= SIMILARITY_THRESHOLD:
                    mentions.append(
                        {
                            "Symbol": symbol,
                            "SymbolToken": token,
                            "Score": similarity,
                            "ProperName": "".join(
                                [
                                    stock["Name"]
                                    for stock in self.stock_data
                                    if stock["Symbol"] == symbol
                                ]
                            ),
                        }
                    )
        doc = self.nlp(tweet)
        for token in doc:
            for proper_name in self.proper_stock_names:
                proper_name_doc = self.nlp(proper_name)
                similarity = token.similarity(proper_name_doc)
                if similarity >= SIMILARITY_THRESHOLD:
                    mentions.append(
                        {
                            "Symbol": "".join(
                                [
                                    stock["Symbol"]
                                    for stock in self.stock_data
                                    if stock["Name"] == proper_name
                                ]
                            ),
                            "ProperName": proper_name,
                            "NameToken": token.text,
                            "Score": similarity,
                        }
                    )
        for chunk in doc.noun_chunks:
            if len(chunk.text.split(" ")) > 1:
                for proper_name in self.proper_stock_names:
                    proper_name_doc = self.nlp(proper_name)
                    similarity = chunk.similarity(proper_name_doc)
                    if similarity >= SIMILARITY_THRESHOLD:
                        mentions.append(
                            {
                                "Symbol": "".join(
                                    [
                                        stock["Symbol"]
                                        for stock in self.stock_data
                                        if stock["Name"] == proper_name
                                    ]
                                ),
                                "ProperName": proper_name,
                                "WordChunk": chunk.text,
                                "Score": similarity,
                            }
                        )

        return mentions

    def _get_symbols(self, stock_data: list[dict]):
        symbols = set()
        for entry in stock_data:
            symbols.add(entry["Symbol"])
        return symbols

    def _get_stock_proper_name(self, stock_data: list[dict]):
        proper_names = set()
        for entry in stock_data:
            proper_names.add(entry["Name"])
        return proper_names

    def _load_data(self, filename):
        with open(filename, "r") as f:
            stock_data = json.load(f)
        return stock_data

    def _send_emails(self, results):
        pass


def main():
    email_outlet = SMTPStockEmailOutlet(
        os.getenv("TICKER_TWEET_EMAIL"),
        os.getenv("TICKER_TWEET_PASSWORD"),
        [],
        "data/s&p-500.json",
    )

    results = email_outlet._analyze_tweet(
        "Apple and Gartner seem to be really at each other right now"
    )
    print(results)
    # print(email_outlet.proper_stock_names)


main()
