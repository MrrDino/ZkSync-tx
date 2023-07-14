import time
import random

import global_constants as gc

from loguru import logger

from mute.mute import MuteIO
from syncswap.syncswap import SyncSwap
from velocore.velocore import Velocore
from helper import get_txt_info, check_gas


def start():

    keys = get_txt_info('keys.txt')

    for key in keys:
        gas = False

        while not gas:
            gas = check_gas()

            if not gas:
                logger.info(f'High gas. Wait {gc.TIMEOUT} sec.')
                time.sleep(gc.TIMEOUT)

        exchange = gc.EXCHANGES[random.randint(0, 2)]

        if exchange == 'SyncSwap':
            swapper = SyncSwap()
        elif exchange == 'Velocore':
            swapper = Velocore()
        else:
            swapper = MuteIO()

        amount = swapper.start_swap(key=key, token0=gc.FROM, token1=gc.TO, pub_key=True, exchange=exchange)

        if gc.SWAP_BACK:
            delay = random.randint(gc.DELAY1[0], gc.DELAY1[1])
            logger.info(f"Swap back. Wait {delay}")
            time.sleep(delay)

            amount = amount / 10 ** 18
            swapper.start_swap(key=key, token0=gc.TO, token1=gc.FROM, amount=amount)

        delay = random.randint(gc.DELAY2[0], gc.DELAY2[1])
        logger.info(f"Change wallet. Wait {delay}")
        time.sleep(delay)


if __name__ == '__main__':
    start()
