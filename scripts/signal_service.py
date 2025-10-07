# scripts/signal_service.py 

"""
Combines capabilities of pull_signal_news and signal_group_reader to automatically receive incoming signal
messages --> filter urls --> add urls to data/data/news_articles.csv 

USAGE: python signal_service.py 
"""

import argparse, logging 
from typing import Optional, Sequence 
from pull_signal_news import *
from signal_group_reader import *


def run(number: str, group_name: str, signal_cli: str,
        log_file: Optional[str], max_minutes: Optional[float]):

    # Run signal_group_reader 

    # Run pull_signal_news to filter urls from log file 

    # add urls to data/data/news_articles.csv 
    
def main(argv: Optional[Sequence[str]]=None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Signal URLs from Group Chats into the UAS News Feed")
    parser.add_argument("--dry_run", action="store_true", help="Fetch and print URLS without touching the CSV store")
    args = parser.parse_args(argv)
    logging_kwargs = {"level": logging.INFO, "format": "%(asctime)s %(levelname)s %(message)s"}
    logging.basicConfig(**logging_kwargs)

if __name__ == "__main__":
    sys.exit(main())