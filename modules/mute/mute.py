import web3
import time

from web3 import Web3
from loguru import logger
from web3.types import ChecksumAddress
from eth_account.signers.local import LocalAccount
from web3.middleware import construct_sign_and_send_raw_middleware

from . import constants as cst
from .abis.router import ROUTER_ABI
from modules.helper import SimpleW3, retry
from modules.global_constants import TOP_UP_WAIT


class MuteIO(SimpleW3):

    def start_swap(self, key: str, token0: str, token1: str, amount: float = None) -> int or None:
        """Функция запуска tokens swap для Mute.io"""

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

    @retry
    def make_swap(
            self,
            w3: Web3,
            amount: int or float,
            account: LocalAccount,
            token0: str = cst.ETH,
            token1: str = cst.USDC
    ):
        """Функция выполнения обмена для Mute.io"""

        token0, token1, signer, router = self.prepare(
            w3=w3,
            token0=token0,
            token1=token1,
            account=account
        )
        token_in = cst.TOKENS[token0.lower()]  # если ETH -> поведение меняется

        #  Если повторный свап -> переводим сумму из ETH в USDC
        if isinstance(amount, float):
            amount = self.get_usd_value(amount=amount, router=router, token0=token1, token1=token0)

        if token_in == 'ETH':
            swap_tx = router.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
                0,
                [token0, token1],
                signer,
                int(time.time()) + 1800,
                [True, False]
            ).build_transaction({
                'gas': 0,
                'from': signer,
                'value': amount,
                'maxFeePerGas': 0,
                'maxPriorityFeePerGas': 0,
                'nonce': w3.eth.get_transaction_count(signer),
            })
        else:
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

            swap_tx = router.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
                amount,
                0,
                [token0, token1],
                signer,
                int(time.time()) + 1800,
                [False, False]
            ).build_transaction({
                'gas': 0,
                'value': 0,
                'from': signer,
                'maxFeePerGas': 0,
                'maxPriorityFeePerGas': 0,
                'nonce': w3.eth.get_transaction_count(signer),
            })

        swap_tx.update(
            {
                'gas': w3.eth.estimate_gas(swap_tx),
                'maxFeePerGas': w3.eth.gas_price,
                'maxPriorityFeePerGas': w3.eth.gas_price
            }
        )

        signed_tx = account.sign_transaction(transaction_dict=swap_tx)
        time.sleep(30)
        status = 0

        try:
            swap_tx = w3.eth.send_raw_transaction(transaction=signed_tx.rawTransaction)
            tx_rec = w3.eth.wait_for_transaction_receipt(swap_tx)
            status = tx_rec['status']  # будет использоваться для переотправки
            logger.info(f'Tx: {swap_tx.hex()}. Status: {status}')
        except Exception as err:
            logger.error(err)

        assert status == 1  # если статус != 1 транзакция не прошла

    @staticmethod
    def get_usd_value(
            amount: float,
            token0: ChecksumAddress,
            token1: ChecksumAddress,
            router: web3.contract.Contract,
    ) -> int:
        """Функция получения курса для пары"""

        amount = int(amount * 10 ** 18)
        quote_info = router.functions.getAmountOut(amount, token0, token1).call()

        quote = int((quote_info[0] * .98))

        return quote

    def prepare(
            self,
            w3: Web3,
            token0: str,
            token1: str,
            account: LocalAccount
    ) -> [
        ChecksumAddress,
        ChecksumAddress,
        ChecksumAddress,
        web3.contract.Contract
    ]:
        """Функция преобразования первичных данных"""

        token0 = self.to_address(token0)
        token1 = self.to_address(token1)
        router = self.get_contract(w3=w3, address=cst.ROUTER, abi=ROUTER_ABI)

        return [token0, token1, account.address, router]
