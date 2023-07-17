import web3
import time
import eth_abi


from web3 import Web3
from loguru import logger
from web3.types import TxParams, ChecksumAddress
from eth_account.signers.local import LocalAccount
from web3.middleware import construct_sign_and_send_raw_middleware

from .abis.pool import POOL_ABI
from . import constants as cst
from .abis.router import ROUTER_ABI
from .abis.factory import FACTORY_ABI
from global_constants import TOP_UP_WAIT
from helper import SimpleW3, retry, get_gas


class SyncSwap(SimpleW3):

    @retry
    def start_swap(
            self,
            key: str,
            token0: str,
            token1: str,
            amount: float = None,
            exchange: str = None,
            pub_key: bool = False
    ) -> int or None:
        """Функция запуска tokens swap для SyncSwap"""

        w3 = self.connect()
        account = self.get_account(w3=w3, key=key)
        w3.middleware_onion.add(construct_sign_and_send_raw_middleware(account))

        if pub_key:
            logger.info(f"Work with \33[{35}m{account.address}\033[0m Exchange: \33[{36}m{exchange}\033[0m")

        if not amount:
            need_msg = True

            while not amount:
                amount = self.get_amount(w3=w3, wallet=account.address)

                if not amount:
                    if need_msg:
                        logger.error(f"Insufficient balance! Address - {account.address}, key - {key}.")
                        need_msg = False
                    time.sleep(TOP_UP_WAIT)

            self.make_swap(w3=w3, amount=amount, account=account, token0=token0, token1=token1)
            return amount
        else:
            self.make_swap(w3=w3, amount=amount, account=account, token0=token0, token1=token1)

    def make_swap(
            self,
            w3: Web3,
            amount: int or float,
            account: LocalAccount,
            token0: str = cst.ETH,
            token1: str = cst.USDC
    ):
        """Функция выполнения обмена для SyncSwap"""

        pool, token0, token1, pool_address, signer = self.preparing(
            w3=w3,
            token0=token0,
            token1=token1,
            account=account
        )
        token_in = cst.TOKENS[token0.lower()]  # если ETH -> поведение меняется
        token_out = 'USDC' if token_in == 'ETH' else 'ETH'

        router = self.get_contract(w3=w3, address=cst.ROUTER, abi=ROUTER_ABI)

        #  Если повторный свап -> переводим сумму из ETH в USDC
        rate = self.get_rate(w3=w3, pool=pool_address)
        if isinstance(amount, float):
            amount = self.get_swap_amount(amount=amount, rate=rate)

        if token_in != 'ETH':

            try:
                approved_tx = self.approve_swap(
                    w3=w3,
                    token=token0,
                    amount=amount,
                    signer=account,
                    sign_addr=signer,
                    spender=cst.ROUTER,
                )

                if approved_tx:
                    gas = get_gas()
                    gas_price = w3.eth.gas_price

                    tx_rec = w3.eth.wait_for_transaction_receipt(approved_tx)

                    fee = self.get_fee(gas_used=tx_rec['gasUsed'], gas_price=gas_price, rate=rate)
                    tx_fee = f"tx fee ${fee}"

                    logger.info(
                        f'||APPROVE| https://www.okx.com/explorer/zksync/tx/{approved_tx.hex()} '
                        f'Gas: {gas} gwei, \33[{36}m{tx_fee}\033[0m'
                    )
                    logger.info('Wait 50 sec.')

                    time.sleep(50)
                else:
                    logger.info("Doesn't need approve. Wait 20 sec.")
                    time.sleep(20)
            except Exception as err:
                logger.error(f"\33[{31}m{err}\033[0m")

        steps = [
            {
                "pool": pool_address,
                "data": eth_abi.encode(
                    ["address", "address", "uint8"],
                    [token0, signer, cst.WITHDRAW_MODE]
                ),
                "callback": cst.ZERO_ADDRESS,
                "callbackData": '0x'
            }
        ]

        paths = [
            {
                'steps': steps,
                'tokenIn': cst.ZERO_ADDRESS if token_in == 'ETH' else token0,
                'amountIn': amount
            }
        ]

        tx = self.create_swap_tx(
            w3=w3,
            paths=paths,
            wallet=signer,
            router=router,
            amount=amount,
            token_in=token_in
        )

        gas_price = w3.eth.gas_price
        tx.update(
            {
                'gas': w3.eth.estimate_gas(tx),
                'maxFeePerGas': gas_price,
                'maxPriorityFeePerGas': gas_price
            }
        )

        signed_tx = account.sign_transaction(transaction_dict=tx)
        logger.info("Swap transaction signed. Wait 30 sec.")
        time.sleep(30)
        status = 0

        try:
            swap_tx = w3.eth.send_raw_transaction(transaction=signed_tx.rawTransaction)
            tx_rec = w3.eth.wait_for_transaction_receipt(swap_tx)

            gas = get_gas()
            status = tx_rec['status']
            fee = self.get_fee(gas_used=tx_rec['gasUsed'], gas_price=gas_price, rate=rate)
            tx_fee = f"tx fee ${fee}"

            logger.info(
                f'||SWAP to {token_out}| https://www.okx.com/explorer/zksync/tx/{swap_tx.hex()} '
                f'Gas: {gas} gwei, \33[{36}m{tx_fee}\033[0m'
            )
        except Exception as err:
            logger.error(f"\33[{31}m{err}\033[0m")

        assert status == 1

    def preparing(self, w3: Web3, token0: str, token1: str, account: LocalAccount) -> [
        web3.contract.Contract,
        LocalAccount,
        ChecksumAddress,
        ChecksumAddress,
        ChecksumAddress,
        ChecksumAddress
    ]:
        """Функция предварительного получения всех необходимых данных"""

        token0 = self.to_address(token0)
        token1 = self.to_address(token1)

        pool = self.get_contract(w3=w3, address=cst.POOL_FACTORY, abi=FACTORY_ABI)
        pool_address = pool.functions.getPool(token0, token1).call()

        return [pool, token0, token1, pool_address, account.address]

    def get_rate(self, w3: Web3, pool: ChecksumAddress) -> float:
        """Функция получения курса в пуле"""

        contract = self.get_contract(w3=w3, address=pool, abi=POOL_ABI)
        reserves = contract.functions.getReserves().call()
        token0 = contract.functions.token0().call()

        if cst.TOKENS[token0.lower()] == 'ETH':
            usd = int(reserves[1] / 10 ** 6) / int(reserves[0] / 10 ** 18)
        else:
            usd = int(reserves[0] / 10 ** 6) / int(reserves[1] / 10 ** 18)

        usd -= usd * .0034

        return usd

    @staticmethod
    def create_swap_tx(
            router: web3.contract.Contract,
            wallet: ChecksumAddress,
            token_in: str,
            amount: int,
            paths: list,
            w3: Web3,
    ) -> TxParams:

        txn = router.functions.swap(
            paths,
            0,
            int(time.time()) + 1800,
        ).build_transaction({
            'gas': 0,
            'from': wallet,
            'maxFeePerGas': 0,
            'maxPriorityFeePerGas': 0,
            'value': amount if token_in == 'ETH' else 0,
            'nonce': w3.eth.get_transaction_count(wallet),
        })

        return txn

    @staticmethod
    def get_swap_amount(amount: float, rate: float, dec: int = 6) -> int:
        """Функция суммы для обмена USDT"""

        return int(amount * rate * (10 ** dec))

    def get_fee(self, gas_used: float, gas_price: int, rate: float) -> float:
        """Функция получения комиссии транзакции в долларах"""

        fee = (gas_used * gas_price) / 10 ** 18
        amount = self.get_swap_amount(amount=fee, rate=rate)

        return round((amount / 10 ** 6), 2)
