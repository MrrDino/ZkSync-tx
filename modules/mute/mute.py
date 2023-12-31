import web3
import time

from web3 import Web3
from loguru import logger
from web3.types import ChecksumAddress
from eth_account.signers.local import LocalAccount
from web3.middleware import construct_sign_and_send_raw_middleware

from . import constants as cst
from .abis.router import ROUTER_ABI
from global_constants import TOP_UP_WAIT
from helper import SimpleW3, retry, get_gas


class MuteIO(SimpleW3):

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
        """Функция запуска tokens swap для Mute.io"""

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
                        logger.error(f"Insufficient balance! Address - {account.address} key - {key}.")
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
        """Функция выполнения обмена для Mute.io"""

        token0, token1, signer, router = self.prepare(
            w3=w3,
            token0=token0,
            token1=token1,
            account=account
        )
        token_in = cst.TOKENS[token0.lower()]  # если ETH -> поведение меняется
        token_out = 'USDC' if token_in == 'ETH' else 'ETH'

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
                    gas = get_gas()
                    gas_price = w3.eth.gas_price

                    tx_rec = w3.eth.wait_for_transaction_receipt(approved_tx)

                    fee = self.get_fee(gas_used=tx_rec['gasUsed'], gas_price=gas_price, router=router)
                    tx_fee = f"tx fee ${fee}"

                    logger.info(
                        f'||APPROVE| https://www.okx.com/explorer/zksync/tx/{approved_tx.hex()} '
                        f'Gas: {gas} gwei, \33[{36}m{tx_fee}\033[0m'
                    )
                    logger.info('Wait 50 sec.')
                    time.sleep(50)
                else:
                    logger.info("Doesn't need approve. Wait 2 sec.")
                    time.sleep(2)
            except Exception as err:
                logger.error(f"\33[{31}m{err}\033[0m")

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

        gas_price = w3.eth.gas_price
        swap_tx.update(
            {
                'gas': w3.eth.estimate_gas(swap_tx),
                'maxFeePerGas': gas_price,
                'maxPriorityFeePerGas': gas_price
            }
        )

        signed_tx = account.sign_transaction(transaction_dict=swap_tx)
        logger.info("Swap transaction signed. Wait 30 sec.")
        time.sleep(30)
        status = 0

        try:
            swap_tx = w3.eth.send_raw_transaction(transaction=signed_tx.rawTransaction)
            tx_rec = w3.eth.wait_for_transaction_receipt(swap_tx)

            gas = get_gas()
            status = tx_rec['status']
            fee = self.get_fee(gas_used=tx_rec['gasUsed'], gas_price=gas_price, router=router)
            tx_fee = f"tx fee ${fee}"

            logger.info(
                f'||SWAP to {token_out}| https://www.okx.com/explorer/zksync/tx/{swap_tx.hex()} '
                f'Gas: {gas} gwei, \33[{36}m{tx_fee}\033[0m'
            )
        except Exception as err:
            logger.error(f"\33[{31}m{err}\033[0m")

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

    def get_fee(
            self,
            gas_price: int,
            gas_used: float,
            router: web3.contract.Contract
    ) -> float:
        """Функция получения комиссии транзакции в долларах"""

        amount = (gas_used * gas_price) / 10 ** 18
        token0 = self.to_address('0x5aea5775959fbc2557cc8789bc1bf90a239d9a91')
        token1 = self.to_address('0x3355df6D4c9C3035724Fd0e3914dE96A5a83aaf4')
        fee = self.get_usd_value(amount=amount, router=router, token0=token0, token1=token1)

        return round((fee / 10 ** 6), 2)
