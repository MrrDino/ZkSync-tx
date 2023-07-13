ETH_NODE = 'https://rpc.ankr.com/eth'

MAX_GAS = 20

FROM = '0x5aea5775959fbc2557cc8789bc1bf90a239d9a91'  # ETH
TO = '0x3355df6D4c9C3035724Fd0e3914dE96A5a83aaf4'  # USDC

# SWAP SIZE
MIN_AMOUNT = .0040783968  # ETH
MAX_AMOUNT = .007646994  # ETH

SWAP_BACK = True  # Нужно ли менять актив обратно

EXCHANGES = {
    0: 'SyncSwap',
    1: 'SpaceFi',
    2: 'Mute'
}

#  Timeouts

TIMEOUT = 10  # время ожидания между проверкой газа

DELAY1 = 60  # время ожидания между свапами
DELAY2 = 60  # время ожидания между кошельками

TOP_UP_WAIT = 60  # время ожидания пополнения баланса