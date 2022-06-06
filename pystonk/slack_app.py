from pystonk import get_conf_path
from pystonk.api.PriceHistoryApi import PriceHistoryApi
from pystonk.api.OptionsChainApi import OptionsChainApi
from pystonk.api.QuoteApi import QuoteApi
from pystonk.reports.WeeklyPriceChangeReport import WeeklyPriceChangeReport
from pystonk.reports.WeeklyOptionsReport import WeeklyOptionsReport
from pystonk.view.ErrorView import ErrorView
from pystonk.view.HelpView import HelpView
from pystonk.view.OptionsChainView import OptionsChainView
from pystonk.view.PriceCheckView import PriceCheckView
from pystonk.view.PriceHistoryView import PriceHistoryView
from pystonk.utils.LoggerMixin import getLogger

from pyhocon import ConfigFactory
from slack_bolt import App
from slack_sdk import WebClient
from typing import Callable, Dict, Tuple

import re

config = ConfigFactory.parse_file(get_conf_path())
logger = getLogger('pystonk')
app = App(
    token=config['slack']['token'],
    signing_secret=config['slack']['secret'],
    logger=logger,
    process_before_response=config['slack']['lambda']
)
slack_web_client = WebClient(token=config['slack']['token'])


def pc_handler(*args) -> Tuple:
    try:
        symbol = args[0].upper()
        api = QuoteApi(config['api_key'])
        price = api.getQuote(symbol)

        return f"{symbol} is currently {round(float(price), 2) if price else 'not found'}", PriceCheckView(symbol, price).show()
    except Exception as e:
        return str(e), ErrorView(str(e)).show()


def ph_handler(*args) -> Tuple:
    try:
        symbol = args[0].upper()
        percent = abs(round(float(args[1]), 2))
        r = WeeklyPriceChangeReport(
            PriceHistoryApi(config['api_key'])
        )
        r.retrieveData(symbol)

        view = PriceHistoryView(
            symbol=symbol,
            percent=percent,
            data=r.generate(percent),
            total_weeks=r.totalWeeks(),
            exceeded_weeks=r.thresholdExceededWeeksTotal(percent),
            longest_weeks=r.longestThresholdExceededWeeks(percent),
            price_change_estimate=r.priceChangeEstimate()
        )

        return f"price history for {symbol} with {percent} threshold", view.show()
    except Exception as e:
        return str(e), ErrorView(str(e)).show()


def oc_handler(*args) -> Tuple:
    try:
        symbol = args[0].upper()
        premium = abs(round(float(args[1]), 2))
        r = WeeklyOptionsReport(
            QuoteApi(config['api_key']),
            OptionsChainApi(config['api_key'])
        )
        r.retrieveData(symbol)

        view = OptionsChainView(
            symbol=symbol,
            premium=premium,
            current_price=r.getMark(),
            data=r.generate(),
            sell_options=r.getStrikePricesForTargetPremium(premium),
            buy_options=r.getStrikePricesForTargetPremium(premium, is_sell=False)
        )

        return f"option chain for {symbol} with {premium} premium", view.show()
    except Exception as e:
        return str(e), ErrorView(str(e)).show()


def parse_command(text: str) -> Tuple:
    text = re.sub(r"<.*>", '', text).strip()
    for regex, handler in commands:
        r = regex.search(text)
        if r:
            return handler, r.groups()
    return None, None


def dispatch_response(ack: Callable, payload: Dict) -> None:
    ack("one moment...")
    slack_responder(payload, None)


@app.event("app_mention")
def receive_mention(ack, event, body):
    logger.debug(f"event : `{event}`")
    logger.debug(f"body : `{body}`")

    dispatch_response(
        ack,
        {
            "f": "respond_mention",
            "p": [event['text'], event['channel']]
        }
    )


def respond_mention(text: str, channel_id: str):
    try:
        handler, args = parse_command(text)
        if not handler:
            text_response = "Invalid command"
            block_response = HelpView().show()
        else:
            response = handler(*args)
            text_response = response[0]
            block_response = response[1]

        logger.debug(f"block : {block_response}")
        logger.debug(f"block length : {len(str(block_response))}")
        logger.debug(f"text : {len(text_response)}")
        slack_web_client.chat_postMessage(
            channel=channel_id,
            blocks=block_response,
            text=text_response
        )
    except Exception as e:
        logger.error(f"Error publishing mention: {e}")


@app.command(re.compile(r"^/pystonk(-dev)?$", re.IGNORECASE | re.ASCII))
def receive_slash_command(ack, event, body):
    logger.debug(f"event : `{event}`")
    logger.debug(f"body : `{body}`")

    dispatch_response(
        ack,
        {
            "f": "respond_slash_command",
            "p": [body['text'], body['user_id'], body['channel_id']]
        }
    )


def respond_slash_command(text: str, user_id: str, channel_id: str):
    try:
        handler, args = parse_command(text)
        if not handler:
            text_response = "Invalid command"
            block_response = HelpView().show()
        else:
            response = handler(*args)
            text_response = response[0]
            block_response = response[1]

        logger.debug(f"block : {block_response}")
        logger.debug(f"block length : {len(str(block_response))}")
        logger.debug(f"text : {len(text_response)}")
        slack_web_client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            blocks=block_response,
            text=text_response
        )
    except Exception as e:
        logger.error(f"Error publishing mention: {e}")


def slack_responder(event, context):
    logger.debug(event)
    logger.debug(context)

    f = globals()[event['f']]
    f(*event['p'])


def start():
    app.start(port=int(config['slack']['port']))


commands = (
    (
        re.compile(r"^pc ([a-zA-Z.]+)$", re.IGNORECASE | re.ASCII),
        pc_handler
    ),
    (
        re.compile(r"^ph ([a-zA-Z.]+) (\d*\.?\d*)$", re.IGNORECASE | re.ASCII),
        ph_handler
    ),
    (
        re.compile(r"^oc ([a-zA-Z.]+) (\d*\.?\d*)$", re.IGNORECASE | re.ASCII),
        oc_handler
    )
)


if __name__ == '__main__':
    start()
