from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

import webbrowser
from .mecenas_contract import MecenasContract
from electroncash.address import ScriptOutput
from electroncash.transaction import Transaction,TYPE_ADDRESS, TYPE_SCRIPT
import electroncash.web as web
from electroncash_gui.qt.amountedit  import BTCAmountEdit
from electroncash.i18n import _
from electroncash_gui.qt.util import *
from electroncash.wallet import Multisig_Wallet
from electroncash.util import NotEnoughFunds
from electroncash_gui.qt.transaction_dialog import show_transaction
from .contract_finder import find_contract
from .mecenas_contract import ContractManager, UTXO, CONTRACT, MODE
from .util import *
import time, json
from math import ceil


class Intro(QDialog, MessageBoxMixin):

    def __init__(self, parent, plugin, wallet_name, password, manager=None):
        QDialog.__init__(self, parent)
        self.main_window = parent
        self.wallet=parent.wallet
        self.plugin = plugin
        self.wallet_name = wallet_name
        self.config = parent.config
        vbox = QVBoxLayout()
        self.setLayout(vbox)
        self.contracts=None
        self.contractTx=None
        self.manager=None
        self.password = None
        self.mode=0
        hbox = QHBoxLayout()
        if is_expired():
            l = QLabel(_("Please update your plugin"))
            l.setStyleSheet("QLabel {color:#ff0000}")
            vbox.addWidget(l)
        l = QLabel("<b>%s</b>"%(_("Manage my Mecenas:")))
        vbox.addWidget(l)

        vbox.addLayout(hbox)
        b = QPushButton(_("Create new Mecenas contract"))
        b.clicked.connect(lambda: self.plugin.switch_to(Create, self.wallet_name, None, self.manager))
        hbox.addWidget(b)
        b = QPushButton(_("Find existing Mecenas contract"))
        b.clicked.connect(self.handle_finding)
        hbox.addWidget(b)
        vbox.addStretch(1)

    def handle_finding(self):
        self.contracts = find_contract(self.wallet)
        if len(self.contracts):
            self.start_manager()
        else:
            self.show_error("You are not a party in any contract yet.")


    def start_manager(self):
        try:
            keypairs, public_keys = self.get_keypairs_for_contracts(self.contracts)
            self.manager = ContractManager(self.contracts, keypairs,public_keys, self.wallet)
            self.plugin.switch_to(Manage, self.wallet_name, self.password, self.manager)
        except Exception as es:
            print(es)
            self.show_error("Wrong wallet.")
            self.plugin.switch_to(Intro,self.wallet_name,None,None)

    def get_keypairs_for_contracts(self, contracts):
        if self.wallet.has_password():
            self.main_window.show_error(_(
                "Contract found! Plugin requires password to operate. It will get access to your private keys."))
            self.password = self.main_window.password_dialog()
            if not self.password:
                return
        keypairs = dict()
        public_keys=[]
        for c in contracts:
            public_keys.append(dict())
            for m in c[MODE]:
                myAddress=c[CONTRACT].addresses[m]
                i = self.wallet.get_address_index(myAddress)
                if not self.wallet.is_watching_only():
                    priv = self.wallet.keystore.get_private_key(i, self.password)
                else:
                    print("watch only")
                    priv = None
                try:
                    public = self.wallet.get_public_keys(myAddress)

                    public_keys[contracts.index(c)][m]=public[0]
                    keypairs[public[0]] = priv
                except Exception as ex:
                    print(ex)

        return keypairs, public_keys


class Create(QDialog, MessageBoxMixin):

    def __init__(self, parent, plugin, wallet_name, password, manager):
        QDialog.__init__(self, parent)
        print("Creating")
        self.main_window = parent
        self.wallet=parent.wallet
        self.plugin = plugin
        self.wallet_name = wallet_name
        self.config = parent.config
        self.password=None
        self.contract=None
        if self.wallet.has_password():
            self.main_window.show_error(_(
                "Plugin requires password. It will get access to your private keys."))
            self.password = parent.password_dialog()
            if not self.password:
                print("no password")
                self.plugin.switch_to(Intro, self.wallet_name,None, None)
        self.fund_domain = None
        self.fund_change_address = None
        self.mecenas_address = self.wallet.get_unused_address()
        self.protege_address=None
        self.cold_address=None
        self.value=0
        index = self.wallet.get_address_index(self.mecenas_address)
        key = self.wallet.keystore.get_private_key(index,self.password)
        self.privkey = int.from_bytes(key[0], 'big')

        if isinstance(self.wallet, Multisig_Wallet):
            self.main_window.show_error(
                "Mecenas is designed for single signature wallet only right now")

        vbox = QVBoxLayout()
        self.setLayout(vbox)
        hbox = QHBoxLayout()
        vbox.addLayout(hbox)
        l = QLabel("<b>%s</b>" % (_("Creatin Mecenas contract:")))
        hbox.addWidget(l)
        hbox.addStretch(1)
        b = QPushButton(_("Home"))
        b.clicked.connect(lambda: self.plugin.switch_to(Intro, self.wallet_name, None, None))
        hbox.addWidget(b)
        l = QLabel(_("Redeem address") + ": auto (this wallet)")  # self.refreshing_address.to_ui_string())
        vbox.addWidget(l)



        grid = QGridLayout()
        vbox.addLayout(grid)

        l = QLabel(_("Protege address: "))
        grid.addWidget(l, 0, 0)

        l = QLabel(_("Value"))
        grid.addWidget(l, 0, 1)

        self.protege_address_wid = QLineEdit()
        self.protege_address_wid.textEdited.connect(self.mecenate_info_changed)
        grid.addWidget(self.protege_address_wid, 1, 0)

        self.deposit_value_wid = BTCAmountEdit(self.main_window.get_decimal_point)
        self.deposit_value_wid.textEdited.connect(self.mecenate_info_changed)
        grid.addWidget(self.deposit_value_wid, 1, 1)

        b = QPushButton(_("Create Mecenas Contract"))
        b.clicked.connect(lambda: self.create_mecenat())
        vbox.addStretch(1)
        vbox.addWidget(b)
        self.create_button = b
        self.create_button.setDisabled(True)
        vbox.addStretch(1)


    def mecenate_info_changed(self, ):
            # if any of the txid/out#/value changes
        try:
            self.protege_address = Address.from_string(self.protege_address_wid.text())
            self.value = self.deposit_value_wid.get_amount()
        except:
            self.create_button.setDisabled(True)
        else:
            self.create_button.setDisabled(False)
            addresses = [self.protege_address, self.mecenas_address]
            self.contract=MecenasContract(addresses)



    def create_mecenat(self, ):

        outputs = [(TYPE_SCRIPT, ScriptOutput(make_opreturn(self.contract.address.to_ui_string().encode('utf8'))),0),
                   (TYPE_ADDRESS, self.mecenas_address, self.value + 190),
                   (TYPE_ADDRESS, self.protege_address, 546)]
        try:
            tx = self.wallet.mktx(outputs, self.password, self.config,
                                  domain=self.fund_domain, change_addr=self.fund_change_address)
            id = tx.txid()
        except NotEnoughFunds:
            return self.show_critical(_("Not enough balance to fund smart contract."))
        except Exception as e:
            return self.show_critical(repr(e))

        # preparing transaction, contract can't give a change
        self.main_window.network.broadcast_transaction2(tx)
        self.create_button.setText("Creating Mecenas Contract...")
        self.create_button.setDisabled(True)
        coin = self.wait_for_coin(id,10)
        self.wallet.add_input_info(coin)
        inputs = [coin]
        outputs = [(TYPE_ADDRESS, self.contract.address, self.value)]
        tx = Transaction.from_io(inputs, outputs, locktime=0)
        tx.version=2
        show_transaction(tx, self.main_window, "Make Mecenas Contract", prompt_if_unsaved=True)
        self.plugin.switch_to(Intro, self.wallet_name, None, None)


    def wait_for_coin(self, id, timeout=10):
        for j in range(timeout):
            coins = self.wallet.get_spendable_coins(None, self.config)
            for c in coins:
                if c.get('prevout_hash') == id:
                    if c.get('value')==self.value+190:
                        return c
            time.sleep(1)
            print("Waiting for coin: "+str(j)+"s")
        return None


class contractTree(MyTreeWidget, MessageBoxMixin):

    def __init__(self, parent, contracts):
        MyTreeWidget.__init__(self, parent, self.create_menu,[
            _('Id'),
            _('Contract expires in: '),
            _('Amount'),
            _('My role')], None, deferred_updates=False)
        self.contracts = contracts
        self.main_window = parent
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setSortingEnabled(True)

    def create_menu(self, position):
        pass

    def update(self):
        if self.wallet and (not self.wallet.thread or not self.wallet.thread.isRunning()):
            return
        super().update()

    def get_selected_id(self):
        utxo = self.currentItem().data(0, Qt.UserRole)
        contract = self.currentItem().data(1, Qt.UserRole)
        m = self.currentItem().data(2, Qt.UserRole)
        if utxo == None:
            index = -1
        else:
            index = contract[UTXO].index(utxo)
        return contract, index, m

    def on_update(self):
        if len(self.contracts) == 1 and len(self.contracts[0][UTXO])==1:
            x = self.contracts[0][UTXO][0]
            item = self.add_item(x, self, self.contracts[0],self.contracts[0][MODE][0])
            self.setCurrentItem(item)
        else:
            for c in self.contracts:
                for m in c[MODE]:
                    contract = QTreeWidgetItem([c[CONTRACT].address.to_ui_string(),'','',role_name(m)])
                    contract.setData(1, Qt.UserRole, c)
                    contract.setData(2,Qt.UserRole, m)
                    self.addChild(contract)
                    for x in c[UTXO]:
                        item = self.add_item(x, contract, c, m)
                        self.setCurrentItem(item)


    def add_item(self, x, parent_item, c, m):
        expiration = self.estimate_expiration(x,c)
        amount = self.parent.format_amount(x.get('value'), is_diff=False, whitespaces=True)
        mode = role_name(m)
        utxo_item = SortableTreeWidgetItem([x['tx_hash'][:10]+'...', expiration, amount, mode])
        utxo_item.setData(0, Qt.UserRole, x)
        utxo_item.setData(1, Qt.UserRole, c)
        utxo_item.setData(2, Qt.UserRole, m)
        parent_item.addChild(utxo_item)

        return utxo_item


    def get_age(self, entry):
        txHeight = entry.get("height")
        currentHeight=self.main_window.network.get_local_height()
        age = (currentHeight-txHeight)//6
        return age

    def estimate_expiration(self, entry, contr):
        """estimates age of the utxo in days. There are 144 blocks per day on average"""
        txHeight = entry.get("height")
        age = self.get_age(entry)
        contract_i_time=ceil((contr[CONTRACT].i_time*512)/(3600))
        print("age, contract itime")
        print(age, contract_i_time)
        if txHeight==0 :
            label = _("Waiting for confirmation.")
        elif (contract_i_time-age) >= 0:
            label = '{0:.2f}'.format((contract_i_time - age)/24) +" days"
        else :
            label = _("Pledge can be taken.")
        return label



class Manage(QDialog, MessageBoxMixin):
    def __init__(self, parent, plugin, wallet_name, password, manager):
        QDialog.__init__(self, parent)
        self.password=password

        self.main_window = parent
        self.wallet=parent.wallet
        self.plugin = plugin
        self.wallet_name = wallet_name
        self.config = parent.config
        self.manager=manager
        vbox = QVBoxLayout()
        self.setLayout(vbox)
        self.fee=1000
        self.contract_tree = contractTree(self.main_window, self.manager.contracts)
        self.contract_tree.on_update()
        vbox.addWidget(self.contract_tree)
        hbox = QHBoxLayout()
        hbox.addStretch(1)
        vbox.addLayout(hbox)
        b = QPushButton(_("Home"))
        b.clicked.connect(lambda: self.plugin.switch_to(Intro, self.wallet_name, None, None))
        hbox.addWidget(b)
        b = QPushButton(_("Create new Mecenas Contract"))
        b.clicked.connect(lambda: self.plugin.switch_to(Create, self.wallet_name, None, self.manager))
        hbox.addWidget(b)
        self.take_pledge_label = _("Take Pledge")
        self.end_label = _("End")
        vbox.addStretch(1)
        self.button = QPushButton("lol")
        self.button.clicked.connect(lambda : print("lol")) # disconnect() throws an error if there is nothing connected
        vbox.addWidget(self.button)
        self.contract_tree.currentItemChanged.connect(self.update_button)
        self.update_button()



    def update_button(self):
        contract, utxo_index, m = self.contract_tree.get_selected_id()
        self.manager.choice(contract, utxo_index, m)
        if m == 0:
            self.button.setText(self.take_pledge_label)
            self.button.clicked.disconnect()
            self.button.clicked.connect(self.pledge)
        else:
            self.button.setText(self.end_label)
            self.button.clicked.disconnect()
            self.button.clicked.connect(self.end)



    def end(self):
        inputs = self.manager.txin
        # Mark style fee estimation
        outputs = [
            (TYPE_ADDRESS, self.manager.contract.addresses[self.manager.mode], self.manager.value)]
        tx = Transaction.from_io(inputs, outputs, locktime=0)
        tx.version = 2
        fee = len(tx.serialize(True)) // 2
        if fee > self.manager.value:
            self.show_error("Not enough funds to make the transaction!")
            return
        outputs = [
            (TYPE_ADDRESS, self.manager.contract.addresses[self.manager.mode], self.manager.value-fee)]
        tx = Transaction.from_io(inputs, outputs, locktime=0)
        tx.version = 2
        if not self.wallet.is_watching_only():
            self.manager.signtx(tx)
            self.manager.completetx(tx)
        show_transaction(tx, self.main_window, "End Mecenas Contract", prompt_if_unsaved=True)
        self.plugin.switch_to(Manage, self.wallet_name, None, None)

    def pledge(self):
        inputs = self.manager.txin
        # Mark style fee estimation
        outputs = [
            (TYPE_ADDRESS, self.manager.contract.address, self.manager.value - self.fee - self.manager.pledge),
            (TYPE_ADDRESS, self.manager.contract.addresses[self.manager.mode], self.manager.pledge)        ]

        tx = Transaction.from_io(inputs, outputs, locktime=0)
        tx.version = 2
        if not self.wallet.is_watching_only():
            self.manager.signtx(tx)
            self.manager.completetx_ref(tx)
        show_transaction(tx, self.main_window, "Pledge", prompt_if_unsaved=True)
        self.plugin.switch_to(Manage, self.wallet_name, None, None)



def role_name(i):
    if i==0:
        return "Protege"
    elif i==1:
        return "Mecenas"
    else:
        return "unknown role"
