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
from modules.helper import SimpleW3, retry
from modules.global_constants import TOP_UP_WAIT


class SyncSwap(SimpleW3):

    @retry
    def start_swap(self, key: str, token0: str, token1: str, amount: float = None) -> int or None:
        """Функция запуска tokens swap для SyncSwap"""

        w3 = self.connect()
        account = self.get_account(w3=w3, key=key)
        w3.middleware_onion.add(construct_sign_and_send_raw_middleware(account))

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
        router = self.get_contract(w3=w3, address=cst.ROUTER, abi=ROUTER_ABI)

        #  Если повторный свап -> переводим сумму из ETH в USDC
        if isinstance(amount, float):
            rate = self.get_rate(w3=w3, pool=pool_address, token_ch=token0)
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
                    tx_rec = w3.eth.wait_for_transaction_receipt(approved_tx)
                    logger.info(f'Approve tx: {approved_tx.hex()}. Status: {tx_rec["status"]}')
                    time.sleep(50)
                else:
                    # Doesn't need approve
                    time.sleep(20)
            except Exception as err:
                logger.error(err)

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

        tx.update(
            {
                'gas': w3.eth.estimate_gas(tx),
                'maxFeePerGas': w3.eth.gas_price,
                'maxPriorityFeePerGas': w3.eth.gas_price
            }
        )

        signed_tx = account.sign_transaction(transaction_dict=tx)
        time.sleep(30)
        status = 0

        try:
            swap_tx = w3.eth.send_raw_transaction(transaction=signed_tx.rawTransaction)
            tx_rec = w3.eth.wait_for_transaction_receipt(swap_tx)
            status = tx_rec['status']  # будет использоваться для переотправки
            logger.info(f'Tx: {swap_tx.hex()}. Status: {status}')
        except Exception as err:
            logger.error(err)

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

    def get_rate(self, w3: Web3, pool: ChecksumAddress, token_ch: ChecksumAddress) -> float:
        """Функция получения курса в пуле"""

        contract = self.get_contract(w3=w3, address=pool, abi=POOL_ABI)
        reserves = contract.functions.getReserves().call()
        token0 = contract.functions.token0().call()

        if cst.TOKENS[token0.lower()] == 'ETH':
            usd = int(reserves[1] / 10 ** 6) / int(reserves[0] / 10 ** 18)
        else:
            usd = int(reserves[0] / 10 ** 6) / int(reserves[1] / 10 ** 18)

        usd -= usd * cst.MULTS[token_ch.lower()]

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
        """Функция суммы для обмена USDT/USDC"""

        return int(amount * rate * (10 ** dec))