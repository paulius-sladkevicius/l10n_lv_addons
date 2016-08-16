# -*- encoding: utf-8 -*-
##############################################################################
#
#    Part of Odoo.
#    Copyright (C) 2016 ITS-1 (<http://www.its1.lv/>)
#                       E-mail: <info@its1.lv>
#                       Address: <Vienibas gatve 109 LV-1058 Riga Latvia>
#                       Phone: +371 67289467
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import base64

from openerp import api, fields, models, _
from openerp.exceptions import UserError
from openerp.addons.base.res.res_bank import sanitize_account_number
from datetime import datetime

from xml.dom.minidom import getDOMImplementation, parseString

class AccountBankStatementImported(models.TransientModel):
    _name = 'account.bank.statement.imported'

    @api.model
    def _default_currency(self):
        user = self.env['res.users'].browse(self._uid)
        currency_id = user.company_id.currency_id.id
        return currency_id

    wizard_id = fields.Many2one('account.bank.statement.import', string='Wizard')
    last_statement = fields.Char('Last statements for selected accounts')
    last_balance_end = fields.Monetary('Ending Balance')
    wrong_balance = fields.Boolean('Wrong Balance')
    currency_id = fields.Many2one('res.currency', string='Currency', default=_default_currency)

class AccountBankStatementImporting(models.TransientModel):
    _name = 'account.bank.statement.importing'

    @api.model
    def _default_currency(self):
        user = self.env['res.users'].browse(self._uid)
        currency_id = user.company_id.currency_id.id
        return currency_id

    wizard_id = fields.Many2one('account.bank.statement.import', string='Wizard')
    current_statement = fields.Char('Statements to import')
    current_balance_start = fields.Monetary('Starting Balance')
    wrong_balance = fields.Boolean('Wrong Balance')
    currency_id = fields.Many2one('res.currency', string='Currency', default=_default_currency)

class AccountBankStatementImport(models.TransientModel):
    _inherit = 'account.bank.statement.import'

    format = fields.Selection([('ofx','.OFX'), ('fidavista','FiDAViSta'), ('iso20022', 'ISO 20022')], string='Format', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency')
    flag = fields.Boolean('Continue Anyway', help='If checked, continues without comparing balances.', default=False)
    wrong_balance = fields.Boolean('Wrong Balance', default=False)
    imported_statement_ids = fields.One2many('account.bank.statement.imported', 'wizard_id', string='Imported Statements')
    importing_statement_ids = fields.One2many('account.bank.statement.importing', 'wizard_id', string='Statements to Import')

    @api.onchange('format', 'data_file')
    def _onchange_data_file(self):
        try:
            datafile = self.data_file
        except:
            raise UserError(_('Wizard in incorrect state. Please hit the Cancel button'))
        if self.format == 'fidavista' and datafile:
            # decoding and encoding for string parsing; parseString() method:
            record = unicode(base64.decodestring(datafile), 'iso8859-4', 'strict').encode('iso8859-4','strict')
            dom = parseString(record)

            # getting date values:
            start_date = dom.getElementsByTagName('StartDate')[0].toxml().replace('<StartDate>','').replace('</StartDate>','')
            end_date = dom.getElementsByTagName('EndDate')[0].toxml().replace('<EndDate>','').replace('</EndDate>','')

            # getting the accountsets to browse through and giving start values for fields:
            accountset = dom.getElementsByTagName('AccountSet')[0]
            wrong_balance = False
            result_imported = []
            bank_obj = self.env['res.partner.bank']
            statement_obj = self.env['account.bank.statement']
            journal_obj = self.env['account.journal']
            cur_obj = self.env['res.currency']

            # testing, whether the Company's bank account is defined in the system:
            acc_no = accountset.getElementsByTagName('AccNo')[0].toxml().replace('<AccNo>','').replace('</AccNo>','')
            test_bnk_acc = bank_obj.search([('acc_number','=',acc_no)])
            if not test_bnk_acc:
                acc_no_list = list(acc_no)
                acc_no_list.insert(4,' ')
                acc_no_list.insert(9,' ')
                acc_no_list.insert(14,' ')
                acc_no_list.insert(19,' ')
                acc_no_list.insert(24,' ')
                acc_no_2 = "".join(acc_no_list)

                test_bnk_acc = bank_obj.search([('acc_number','=',acc_no_2)])

            # getting Statement Reference:
            statement_name = acc_no + ' ' + start_date+ ':' + end_date

            # getting and checking balances:
            balance_start = accountset.getElementsByTagName('OpenBal')[0].toxml().replace('<OpenBal>','').replace('</OpenBal>','')
            if test_bnk_acc:
                journals = journal_obj.search([('bank_account_id','=',test_bnk_acc.id)])
                bank_statement = statement_obj.search([('journal_id', 'in', [j.id for j in journals])], order='date desc', limit=1)
                if bank_statement:
                    if bank_statement.balance_end_real != float(balance_start):
                        wrong_balance = True
                    datas_imported = {
                        'last_statement': bank_statement.name,
                        'last_balance_end': bank_statement.balance_end_real,
                        'wrong_balance': wrong_balance
                    }
                    if bank_statement.currency_id:
                        datas_imported.update({
                            'currency_id': bank_statement.currency_id.id
                        })
                    result_imported.append((0, 0, datas_imported))

            # creating values for already imported data:

            datas_importing = {
                'current_statement': statement_name,
                'current_balance_start': float(balance_start),
                'wrong_balance': wrong_balance
            }

            # get importing currency
            currency = accountset.getElementsByTagName('Ccy')[0].toxml().replace('<Ccy>','').replace('</Ccy>','')
            currency_c = cur_obj.search([('name','=',currency)], limit=1)
            if not currency_c:
                currency_c = cur_obj.search([('name','=',currency), ('active','=',False)], limit=1)
                if currency_c:
                    currency_c.write({'active': True})
            if currency_c:
                datas_importing.update({
                    'currency_id': currency_c.id
                })
                self.currency_id = currency_c.id

            self.imported_statement_ids = result_imported 
            self.importing_statement_ids = [(0, 0, datas_importing)]
            self.wrong_balance = wrong_balance


    def fidavista_parsing(self, data_file):
        # decoding and encoding for string parsing; parseString() method:
        record = unicode(data_file, 'iso8859-4', 'strict').encode('iso8859-4','strict')
        dom = parseString(record)

        journal_obj = self.env['account.journal']
        bs_obj = self.env['account.bank.statement']
        cur_obj = self.env['res.currency']
        bank_obj = self.env['res.partner.bank']

        # getting start values:
        start_date = dom.getElementsByTagName('StartDate')[0].toxml().replace('<StartDate>','').replace('</StartDate>','')
        end_date = dom.getElementsByTagName('EndDate')[0].toxml().replace('<EndDate>','').replace('</EndDate>','')

        accountset = dom.getElementsByTagName('AccountSet')[0]
        account_number = accountset.getElementsByTagName('AccNo')[0].toxml().replace('<AccNo>','').replace('</AccNo>','')
        currency_code = accountset.getElementsByTagName('Ccy')[0].toxml().replace('<Ccy>','').replace('</Ccy>','')
        balance_start = accountset.getElementsByTagName('OpenBal')[0].toxml().replace('<OpenBal>','').replace('</OpenBal>','')
        balance_end_real = accountset.getElementsByTagName('CloseBal')[0].toxml().replace('<CloseBal>','').replace('</CloseBal>','')

        # checking balances:
        test_bnk_acc = bank_obj.search([('acc_number','=',account_number)], limit=1)
        if not test_bnk_acc:
            account_number_list = list(account_number)
            account_number_list.insert(4,' ')
            account_number_list.insert(9,' ')
            account_number_list.insert(14,' ')
            account_number_list.insert(19,' ')
            account_number_list.insert(24,' ')
            account_number_2 = "".join(account_number_list)
            test_bnk_acc = bank_obj.search([('acc_number','=',account_number_2)], limit=1)
        if test_bnk_acc:
            journals = journal_obj.search([('bank_account_id','=',test_bnk_acc.id)])
            test_bs = bs_obj.search([('journal_id','in',[j.id for j in journals])], order='date desc', limit=1)
            if test_bs and test_bs.balance_end_real != float(balance_start) and self.flag == False:
                raise UserError(_("The Ending Balance of the last Bank Statement (by date) imported for the Bank Account '%s' is not equal to the Starting Balance of this document. If this is OK with you, check the 'Continue Anyway' box and try to import again.") %(account_number))

        svals = {
            'name': account_number + ' ' + start_date + ':' + end_date,
            'date': end_date,
            'balance_start': float(balance_start),
            'balance_end_real': float(balance_end_real),
            'transactions': []
        }

        # getting elements for account.bank.statement.line:
        statement_lines = accountset.getElementsByTagName('TrxSet')
        for line in statement_lines:
            # checking transaction types:
            type_name_tag = line.getElementsByTagName('TypeName')

            # getting date, name, ref and amount
            line_date = line.getElementsByTagName('BookDate')[0].toxml().replace('<BookDate>','').replace('</BookDate>','')
            pmt_info = line.getElementsByTagName('PmtInfo')
            if pmt_info:
                line_name = pmt_info[0].toxml().replace('<PmtInfo>','').replace('</PmtInfo>','')
            if (not pmt_info) and type_name_tag:
                line_name = type_name_tag[0].toxml().replace('<TypeName>','').replace('</TypeName>','')
            line_ref = line.getElementsByTagName('BankRef')[0].toxml().replace('<BankRef>','').replace('</BankRef>','')
            line_amount = float(line.getElementsByTagName('AccAmt')[0].toxml().replace('<AccAmt>','').replace('</AccAmt>',''))
            cord = line.getElementsByTagName('CorD')[0].toxml().replace('<CorD>','').replace('</CorD>','')
            if cord == 'D':
                line_amount *= (-1)

            # getting Partner and Currency data
            line_cur = False
            line_amount_cur = 0.0
            partner = False
            partner_name = False
            partner_reg_id = False
            partner_bank_account = False
            bank_account = False
            account_id = False
            bank_name = False
            bank_bic = False
            cPartySet = line.getElementsByTagName('CPartySet')
            if cPartySet:
                # currency data:
                line_cur_tag = cPartySet[0].getElementsByTagName('Ccy')
                if line_cur_tag:
                    line_cur_txt = line_cur_tag[0].toxml().replace('<Ccy>','').replace('</Ccy>','').replace('<Ccy/>','')
                    if line_cur_txt:
                        line_cur = cur_obj.search([('name','=',line_cur_txt)], limit=1)
                line_amount_cur_tag = cPartySet[0].getElementsByTagName('Amt')
                if line_amount_cur_tag:
                    line_amount_cur = line_amount_cur_tag[0].toxml().replace('<Amt>','').replace('</Amt>','').replace('<Amt/>','')
                    line_amount_cur = float(line_amount_cur)

                # partner data:
                partner_name_tag = cPartySet[0].getElementsByTagName('Name')
                if partner_name_tag:
                    partner_name = partner_name_tag[0].toxml().replace('<Name>','').replace('</Name>','').replace('<Name/>','').replace("&quot;","'")
                partner_reg_id_tag = cPartySet[0].getElementsByTagName('LegalId')
                if partner_reg_id_tag:
                    partner_reg_id = partner_reg_id_tag[0].toxml().replace('<LegalId>','').replace('</LegalId>','').replace('<LegalId/>','')
                partner_bank_account_tag = cPartySet[0].getElementsByTagName('AccNo')
                if partner_bank_account_tag:
                    partner_bank_account = partner_bank_account_tag[0].toxml().replace('<AccNo>','').replace('</AccNo>','').replace('<AccNo/>','')

                # testing, whether it's possible to get partner (also type and account) from the system:
                bank_account = bank_obj.search([('acc_number','=',partner_bank_account)], limit=1)
                if (not bank_account) and partner_bank_account:
                    partner_bank_account_list = list(partner_bank_account)
                    partner_bank_account_list.insert(4,' ')
                    partner_bank_account_list.insert(9,' ')
                    partner_bank_account_list.insert(14,' ')
                    partner_bank_account_list.insert(19,' ')
                    partner_bank_account_list.insert(24,' ')
                    partner_bank_account_2 = "".join(partner_bank_account_list)
                    bank_account = bank_obj.search([('acc_number','=',partner_bank_account_2)], limit=1)
                if bank_account:
                    partner = bank_account.partner_id
                if (not bank_account) and (partner_reg_id):
                    partners = self.env['res.partner'].search([('vat','ilike',partner_reg_id)])
                    if len([p.id for p in partners]) == 1:
                        partner = partners
                # setting account if partner found:
                if partner:
                    if cord == 'C':
                        account_id = partner.property_account_receivable_id.id
                    if cord == 'D':
                        account_id = partner.property_account_payable_id.id
                # getting bank data:
                bank_name_tag = cPartySet[0].getElementsByTagName('BankName')
                if bank_name_tag:
                    bank_name = bank_name_tag[0].toxml().replace('<BankName>','').replace('</BankName>','').replace('<BankName/>','')
                bank_bic_tag = cPartySet[0].getElementsByTagName('BankCode')
                if bank_bic_tag:
                    bank_bic = bank_bic_tag[0].toxml().replace('<BankCode>','').replace('</BankCode>','').replace('<BankCode/>','')

            # getting Transaction Types
            type_code = False
            type_code_tag = line.getElementsByTagName('TypeCode')
            if type_code_tag:
                type_code = type_code_tag[0].toxml().replace('<TypeCode>','').replace('</TypeCode>','')
            if (not type_code_tag) and type_name_tag:
                type_code = type_name_tag[0].toxml().replace('<TypeName>','').replace('</TypeName>','')
            if not partner:
                config_obj = self.env['account.bank.transaction.type']
                config = config_obj.search([('name','=',type_code)], limit=1)
                if config:
                    account_id = config.account_id.id

            svals['transactions'].append({
                'date': line_date,
                'name': line_name,
                'ref': line_ref,
                'amount': line_amount,
                'amount_currency': line_amount_cur,
                'currency_id': line_cur and line_cur.id or False,
                'partner_name': partner_name,
                'account_number': partner_bank_account,
                'partner_bank_account': partner_bank_account,
                'partner_reg_id': partner_reg_id,
                'partner_id': partner and partner.id or False,
                'transaction_type': type_code,
                'bank_account_id': bank_account and bank_account.id or False,
                'account_id': account_id,
                'bank_name': bank_name,
                'bank_bic': bank_bic
            })

        stmts_vals = [svals]
        return currency_code, account_number, stmts_vals


    def iso20022_parsing(self, data_file):
        # decoding and encoding for string parsing; parseString() method:
        record = unicode(data_file, 'iso8859-4', 'strict').encode('iso8859-4','strict')
        dom = parseString(record)

        statements = dom.getElementsByTagName('Stmt') or []
        if not statements:
            statements = dom.getElementsByTagName('Rpt') or []

        cur_obj = self.env['res.currency']

        currency_code = False
        account_number = False
        stmts_vals = []
        for statement in statements:
            # getting start values:
            account_tag = statement.getElementsByTagName('Acct')[0]
            account_number = account_tag.getElementsByTagName('IBAN')[0].toxml().replace('<IBAN>','').replace('</IBAN>','')
            name = account_number
            cur_tag = account_tag.getElementsByTagName('Ccy')
            if cur_tag:
                currency_code = cur_tag[0].toxml().replace('<Ccy>','').replace('</Ccy>','')
            start_date = False
            end_date = False
            ft_date_tag = statement.getElementsByTagName('FrDtTm')
            if ft_date_tag:
                start_datetime = ft_date_tag[0].getElementsByTagName('FrDtTm')[0].toxml().replace('<FrDtTm>','').replace('</FrDtTm>','')
                end_datetime = ft_date_tag[0].getElementsByTagName('ToDtTm')[0].toxml().replace('<ToDtTm>','').replace('</ToDtTm>','')
                start_date = datetime.strftime(datetime.strptime(start_datetime, '%Y-%m-%dT%H:%M:%SZ').date(), '%Y-%m-%d')
                end_date = datetime.strftime(datetime.strptime(end_datetime, '%Y-%m-%dT%H:%M:%SZ').date(), '%Y-%m-%d')
                name += (' ' + start_date + ':' + end_date)

            # getting balances:
            balance_start = 0.0
            balance_end_real = 0.0
            balances = statement.getElementsByTagName('Bal')
            for b in balances:
                balance_amount = 0.0
                amount_tags = b.getElementsByTagName('Amt')
                cl_amount_tag = False
                credit_line = b.getElementsByTagName('CdtLine')
                if credit_line:
                    cl_amount_tag = credit_line[0].getElementsByTagName('Amt')
                    cl_amount_tag = cl_amount_tag and cl_amount_tag[0] or False
                for amt in amount_tags:
                    if amt != cl_amount_tag:
                        balance_amount = float(amt.toxml().replace('<Amt>','').replace('</Amt>',''))
                cd_ind = b.getElementsByTagName('CdtDbtInd')[0].replace('<CdtDbtInd>','').replace('</CdtDbtInd>','')
                if cd_ind == 'DBIT':
                    balance_amount *= (-1)
                btype = b.getElementsByTagName('Tp')[0]
                type_code = btype.getElementsByTagName('CdOrPrtry')[0].getElementsByTagName('Cd')[0].toxml().replace('<Cd>','').replace('</Cd>','')
                found = False
                if type_code == 'OPBD':
                    balance_start = balance_amount
                    found = True
                if type_code == 'CLBD':
                    balance_end_real = balance_amount
                    found = True
                if not found:
                    bsubtype = btype.getElementsByTagName('SubType')
                    if bsubtype:
                        subtype_code = bsubtype[0].getElementsByTagName('Cd')[0].toxml().replace('<Cd>','').replace('</Cd>','')
                        if subtype_code == 'OPBD':
                            balance_start = balance_amount
                        if subtype_code == 'CLBD':
                            balance_end_real = balance_amount

            svals = {
                'name': name,
                'date': end_date,
                'balance_start': balance_start,
                'balance_end_real': balance_end_real,
                'transactions': []
            }

            # getting line data:
            entries = statement.getElementsByTagName('Ntry')
            for entry in entries:
                # getting date:
                line_date = False
                date_tag = entry.getElementsByTagName('BookgDt')
                if not date_tag:
                    date_tag = entry.getElementsByTagName('ValDt')
                if date_tag:
                    line_date = date_tag[0].getElementsByTagName('Dt')[0].toxml().replace('<Dt>','').replace('</Dt>','')

                # getting reference and unique id:
                line_ref = False
                unique_import_id = False
                ref_tag = entry.getElementsByTagName('NtryRef')
                if ref_tag:
                    line_ref = ref_tag[0].toxml().replace('<NtryRef>','').replace('</NtryRef>','')
                refs_uref_tag = False
                refs_tag = entry.getElementsByTagName('Refs')
                if refs_tag:
                    refs_uref_tag = refs_tag[0].getElementsByTagName('AcctSvcrRef')
                    refs_uref_tag = refs_uref_tag and refs_uref_tag[0] or False
                    refs_ref_tag = refs_tag[0].getElementsByTagName('Reference')
                    if refs_ref_tag and (not line_ref):
                        line_ref = refs_ref_tag[0].toxml().replace('<Reference>','').replace('</Reference>','')
                uref_tags = entry.getElementsByTagName('AcctSvcrRef')
                for urt in uref_tags:
                    if urt != refs_uref_tag:
                        unique_import_id = urt.toxml().replace('<AcctSvcrRef>','').replace('</AcctSvcrRef>','')
                if (not unique_import_id) and refs_uref_tag:
                    unique_import_id = refs_uref_tag.toxml().replace('<AcctSvcrRef>','').replace('</AcctSvcrRef>','')
                cdtr_refs_tag = entry.getElementsByTagName('CdtrRefInf')
                if cdtr_refs_tag:
                    cref_tag = cdtr_refs_tag[0].getElementsByTagName('Ref')
                    if cref_tag:
                        line_ref = cref_tag[0].toxml().replace('<Ref>','').replace('</Ref>','')
                if (not line_ref) and unique_import_id:
                    line_ref = unique_import_id

                # getting transaction type:
                type_code = False
                tx_dtls_btc_tag = False
                tx_dtls_tag = entry.getElementsByTagName('TxDtls')
                if tx_dtls_tag:
                    tx_dtls_btc_tag = tx_dtls_tag[0].getElementsByTagName('BkTxCd')
                    tx_dtls_btc_tag = tx_dtls_btc_tag and tx_dtls_btc_tag[0] or False
                btc_tags = entry.getElementsByTagName('BkTxCd')
                for btc in btc_tags:
                    if btc != tx_dtls_btc_tag:
                        type_code_tag = btc.getElementsByTagName('SubFmlyCd')
                        if type_code_tag:
                            type_code = type_code_tag[0].toxml().replace('<SubFmlyCd>','').replace('</SubFmlyCd>','')

                # getting amount and currency:
                line_cd_ind = False
                entr_details_tag = entry.getElementsByTagName('NtryDtls')
                edt_cd_tgs = []
                if entr_details_tag:
                    edt_cd_tags = entr_details_tag[0].getElementsByTagName('CdtDbtInd')
                    edt_cd_tgs = [ecdt for ecdt in edt_cd_tags]
                entry_cd_tags = entry.getElementsByTagName('CdtDbtInd')
                for ecd in entry_cd_tags:
                    if ecd not in edt_cd_tgs:
                        line_cd_ind = ecdt.toxml().replace('<CdtDbtInd>','').replace('</CdtDbtInd>','')
                line_amount = 0.0
                line_amount_cur = 0.0
                line_cur = False
                amt_tag = False
                amt_details_tag = entry.getElementsByTagName('AmtDtls')
                if amt_details_tag:
                    inst_amt_tag = amt_details_tag[0].getElementsByTagName('InstdAmt')
                    if inst_amt_tag:
                        amt_cur_tag = inst_amt_tag[0].getElementsByTagName('Amt')[0]
                        line_amount_cur = float(amt_cur_tag.firstChild.nodeValue)
                        if line_cd_ind == 'DBIT':
                            line_amount_cur *= (-1)
                        line_cur_code = amt_cur_tag.attributes['Ccy'].value
                        line_cur = cur_obj.search([('name','=',line_cur_code)], limit=1)
                    trans_amt_tag = amt_details_tag[0].getElementsByTagName('TxAmt')
                    if trans_amt_tag:
                        amt_tag = trans_amt_tag[0].getElementsByTagName('Amt')
                if (not amt_details_tag) or (amt_details_tag and (not amt_tag)):
                    amt_tag = entry.getElementsByTagName('Amt')
                if amt_tag:
                    line_amount = float(amt_tag[0].firstChild.nodeValue)
                    if line_cd_ind == 'DBIT':
                        line_amount *= (-1)

                # getting bank account:




                svals['transactions'].append({
                    'unique_import_id': unique_import_id,
                    'date': line_date,
#                    'name': line_name,
                    'ref': line_ref,
                    'amount': line_amount,
                    'amount_currency': line_amount_cur,
                    'currency_id': line_cur and line_cur.id or False,
#                    'partner_name': partner_name,
#                    'account_number': partner_bank_account,
#                    'partner_bank_account': partner_bank_account,
#                    'partner_reg_id': partner_reg_id,
#                    'partner_id': partner and partner.id or False,
                    'transaction_type': type_code,
#                    'bank_account_id': bank_account and bank_account.id or False,
#                    'account_id': account_id,
#                    'bank_name': bank_name,
#                    'bank_bic': bank_bic
                })

            stmts_vals.append(svals)

        return currency_code, account_number, stmts_vals


    def _complete_stmts_vals(self, stmts_vals, journal, account_number):
        res = super(AccountBankStatementImport, self)._complete_stmts_vals(stmts_vals, journal, account_number)
        ba_obj = self.env['res.partner.bank']
        bank_obj = self.env['res.bank']
        for st_vals in res:
            for line_vals in st_vals['transactions']:
                # update bank account and save partner if possible:
                if (not line_vals.get('partner_id', False)) and line_vals.get('partner_reg_id'):
                    partners = self.env['res.partner'].search([('vat','ilike',line_vals['partner_reg_id'])])
                    if len([p.id for p in partners]) == 1:
                        line_vals['partner_id'] = partners.id
                if line_vals.get('bank_account_id', False):
                    bank_account = ba_obj.browse(line_vals['bank_account_id'])
                    if (not bank_account.partner_id) and line_vals.get('partner_id', False):
                        bank_account.write({'partner_id': line_vals['partner_id']})
                    if (not bank_account.bank_id) and (line_vals.get('bank_name', False) or line_vals.get('bank_bic', False)):
                        bank_name = line_vals.get('bank_name', False) or line_vals.get('bank_bic', False)
                        bank_bic = line_vals.get('bank_bic', False)
                        bank = bank_obj.search([('bic','=',bank_bic)], limit=1)
                        if not bank:
                            bank = bank_obj.search([('name','=',bank_name)], limit=1)
                        if not bank:
                            bank = bank_obj.create({
                                'name': bank_name,
                                'bic': bank_bic
                            })
                        bank_account.write({'bank_id': bank.id})
                line_vals.pop('bank_name')
                line_vals.pop('bank_bic')
        return res


    def _parse_file(self, data_file):
        if self.format == 'fidavista':
            return self.fidavista_parsing(data_file)
        elif self.format == 'iso20022':
            return self.iso20022_parsing(data_file)
        else:
            return super(AccountBankStatementImport, self)._parse_file()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: