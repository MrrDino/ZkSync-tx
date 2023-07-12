import time
import random

import global_constants as gc

from mute.mute import MuteIO
from spacefi.spacefi import SpaceFi
from syncswap.syncswap import SyncSwap
from helper import get_txt_info, check_gas


def start():

    keys = get_txt_info('keys.txt')

    for key in keys:
        gas = False

        while not gas:
            gas = check_gas()

            if not gas:
                time.sleep(gc.TIMEOUT)

        exchange = gc.EXCHANGES[random.randint(0, 2)]

        if exchange == 'SyncSwap':
            swapper = SyncSwap()
        elif exchange == 'SpaceFi':
            swapper = SpaceFi()
        else:
            swapper = MuteIO()

        amount = swapper.start_swap(key=key, token0=gc.FROM, token1=gc.TO)

        if gc.SWAP_BACK:
            time.sleep(gc.DELAY1)

            amount = amount / 10 ** 18
            swapper.start_swap(key=key, token0=gc.TO, token1=gc.FROM, amount=amount)

        time.sleep(gc.DELAY2)


if __name__ == '__main__':
    start()
