import time
import telnetlib
import logging
import threading
import datetime
import pytz
import os
from telegram import __version__ as TG_VER
try:
    from telegram import __version_info__
except ImportError:
    __version_info__ = (0, 0, 0, 0, 0)  # type: ignore[assignment]
if __version_info__ < (20, 0, 0, "alpha", 1):
    raise RuntimeError(
        f"This example is not compatible with your current PTB version {TG_VER}. To view the" 
        f"{TG_VER} version of this example, "
        f"visit https://docs.python-telegram-bot.org/en/v{TG_VER}/examples.html"
    )
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

PORT = 6303         # NNTP-Server Port
HOST = "127.0.0.1"  # NNTP-Server IP
TOKEN = ""          # TG-BOT Token
UPDATE_TIMER = 15   # New MSG Check Timer in Minutes
""" Server Msg when connecting NNTP-Server. """
SERVER_HEADER = b"201 FBB NNTP server ready at MD2BBS.#SAW.SAA.DEU.EU\r\n"

HOUSEKEEPING_MSG = "<pre>"\
                    "***************************************************************\r\n"\
                    "* -- Bitte warten, das tägliche Housekeeping läuft grade ! --\r\n"\
                    "* Das Housekeeping kann unter Umständen einige Minuten dauern.\r\n"\
                    "* du wirst benachrichtigt wenn der Sync abgeschlossen ist."\
                    "</pre>"
USER = {}


class NNTP(object):
    def __init__(self):
        # Telnet NNTP
        self.update_Info_new = ""
        self.tn_timeout = 60
        self.tn_server_head = SERVER_HEADER
        self.group_index = {}


        try:
            self.tn = telnetlib.Telnet(HOST, PORT)
            self.tn.read_until(self.tn_server_head, self.tn_timeout)
        except EOFError or TimeoutError:
            logging.error("INIT-Telnet>Telnet connection to NNTP Server failed")
            raise EOFError
        """
        if not self.update_group_index():
            logging.error("INIT-get_group_index>Telnet connection to NNTP Server failed")
            raise EOFError
        """
        logging.info("INIT NNTP Done.")

    def tn_is_connected(self):
        try:
            self.tn_flush_read_buf()
        except EOFError:
            logging.info("tn_is_connected> Try reconnecting NNTP Server")
            try:
                self.tn = telnetlib.Telnet(HOST, PORT)
                self.tn.read_until(self.tn_server_head, self.tn_timeout)
            except EOFError or TimeoutError:
                logging.error("tn_is_connected> Try reconnecting NNTP Server failed !")
                raise EOFError

    def tn_flush_read_buf(self):
        try:
            while self.tn.read_very_eager():
                logging.warning("Flushing Telnet Read Buffer !!")
                time.sleep(0.2)
        except EOFError:
            raise EOFError

    def update_group_index(self):                   # Called fm Outside
        """
        Init & Update
        """
        logging.info("NNTP Update Start.")
        self.update_Info_new = ""
        try:
            self.tn_is_connected()
        except EOFError:
            return False

        self.tn.write(b"LIST\r\n")
        buf = self.tn.read_until(b".\r\n")

        if buf[:3] == b'215':
            groups = buf.split(b'\r\n')
            groups = groups[1:len(groups) - 2]

            for el in groups:
                temp = el.split(b' ')
                if temp[0] in self.group_index.keys():          # Update
                    grp_ind = self.group_index[temp[0]][0]
                    if grp_ind[1:] == [temp[2], temp[1]]:
                        logging.debug("Update List {} > No Upates".format(str(temp[0].decode('UTF-8'))))
                    else:
                        g_buf = self.get_group_details(temp[0])
                        if g_buf:
                            logging.info("Update List {}".format(str(temp[0].decode('UTF-8'))))
                            self.update_Info_new += temp[0].decode('UTF-8') + " "
                            # self.group_index[temp[0]] = [g_buf, {}]
                            # self.group_index[temp[0]] = [g_buf, dict(self.group_index[temp[0]][1])]
                            self.group_index[temp[0]][0] = g_buf
                            self.update_headers(temp[0])
                else:                                           # INIT
                    logging.info("Update List {} > INIT".format(str(temp[0].decode('UTF-8'))))
                    self.update_Info_new += temp[0].decode('UTF-8') + " "
                    g_buf = self.get_group_details(temp[0])
                    self.group_index[temp[0]] = [g_buf, {}]
                    self.update_headers(temp[0])
            logging.info("NNTP Update erfolgreich beendet..")
            return True
        logging.warning("NNTP Update fehlgeschlagen !!")
        return False

    def get_group_details(self, group):
        self.tn.write(b'GROUP ' + group + b'\r\n')
        buf = self.tn.read_until(group + b'\r\n')
        buf = buf.split(b' ')
        if buf[0] == b'211':
            return buf[1:len(buf) - 1]
        return []

    def update_grp_index(self, key, data):
        if self.group_index[key][0] != data:
            self.group_index[key][0] = data

    def update_headers(self, grp):
        logging.debug("Read Headers in Group: " + str(grp))
        self.update_grp_index(grp, self.get_group_details(grp))
        if int(self.group_index[grp][0][0]):
            new_keys = []
            for n in range(int(self.group_index[grp][0][0])):
                if not n:
                    self.tn.write(b'STAT ' + self.group_index[grp][0][1] + b'\r\n')
                else:
                    self.tn.write(b'NEXT\r\n')
                buf = self.tn.read_until(b'\r\n')
                logging.debug(buf)
                buf = buf.split(b' ')
                msg_id = buf[1]
                if buf[0] == b'223':
                    new_keys.append(msg_id)
                    if msg_id not in self.group_index[grp][1].keys():
                        logging.debug("Get Headers for Msg: " + str(msg_id))
                        self.tn.write(b'HEAD ' + msg_id + b'\r\n')
                        self.tn.read_until(b'head follows\r\n')  # if buf.split(b' ')[0] == b'221':  ###############
                        buf = self.tn.read_until(b'Message-ID:')
                        buf += self.tn.read_until(b'>')
                        self.tn.read_until(b'\r\n\r\n')
                        self.tn.read_until(b'.\r\n')
                        buf = buf.split(b'\r\n')
                        tmp = {'Received': []}
                        for el in buf:
                            if b'Received: from' in el:
                                tmp['Received'].append(
                                    el.replace(b'Received: from ', b'').decode('UTF-8', 'ignore'))
                            else:
                                key = el.split(b':')[0].decode('UTF-8')
                                tmp[key] = el[len(key) + 2:].decode('UTF-8', 'ignore')
                        self.group_index[grp][1][msg_id] = dict(tmp)
                    else:
                        logging.debug("Skip Headers for Msg: " + str(msg_id))
            # print("Vorher: " + str(len(list(self.group_index[grp][1].keys()))))
            # print("-: " + str(self.group_index[grp][1]))
            for el in list(self.group_index[grp][1].keys()):
                if el not in new_keys:
                    del self.group_index[grp][1][el]
                    logging.info("Delete Headers for Msg: " + str(el))
            # print("Nachher: " + str(len(list(self.group_index[grp][1].keys()))))
            # print("-: " + str(self.group_index[grp][1]))

    def get_msg(self, msg_id=(b'WETTER', b'42')):               # Called fm Outside
        """msg_id group, msg_id"""
        try:
            self.tn_is_connected()
        except EOFError:
            return False
        if self.get_group_details(msg_id[0]):
            self.tn.write(b'ARTICLE ' + msg_id[1] + b'\r\n')
            buf = self.tn.read_until(b'\r\n')
            if buf.split(b' ')[0] == b'220':
                buf = self.tn.read_until(b'.\r\n')
                while True:
                    time.sleep(0.5)
                    b = self.tn.read_very_eager()
                    if b:
                        buf += b
                    else:
                        break
                return buf.decode('UTF-8', 'ignore')
            # elif buf.split(b' ')[0] == b'430':
                # TODO Del Msg frm Msg Index
        logging.error("NNTP.get_msg msg_id: {}".format(msg_id))
        return False


class TgBot(object):
    def __init__(self):
        try:
            logging.info("Init NNTP Modul")
            self.nntp = NNTP()
        except EOFError:
            logging.error("NNTP Modul init failed ...")
            raise EOFError
        self.nntp_th = threading.Thread(target=self.nntp.update_group_index)
        self.nntp_th.start()
        self.housekeeping_tr = True
        self.max_msg_len = 4096
        self.app = Application.builder().token(TOKEN).build()
        #self.app.add_handler(CommandHandler("h", self.test))
        #self.app.add_handler(MessageHandler(filters.Regex(r'^(/test_[\d]_[\d]+)$'), self.test))
        # --- Link Kommandos
        self.app.add_handler(MessageHandler(filters.Regex(r'^(/T_[\d]+)$'), self.list_headers))
        self.app.add_handler(MessageHandler(filters.Regex(r'^(/R[\d]+_[\d]+)$'), self.read_msg))
        # --- Kommandos
        self.app.add_handler(CommandHandler("l", self.list_groups))
        self.app.add_handler(CommandHandler("n", self.list_new_msg))
        # self.app.add_handler(CommandHandler("i", self.info))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.footer))
        # --- Crone Jobs
        # - Update Check
        self.app.job_queue.run_repeating(self.sync_fbb_crone, UPDATE_TIMER * 60)
        # - Reset 1 täglich nach Housekeeping
        self.app.job_queue.run_daily(self.housekeeping,
                                     time=datetime.time(hour=2, minute=15, second=00,
                                                        tzinfo=pytz.timezone('Europe/Berlin')),
                                     days=(0, 1, 2, 3, 4, 5, 6))
        # -------------------------------------------------
        # Run the bot until the user presses Ctrl-C
        self.app.run_polling()

    async def footer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        out = "Themen Übersicht -> /l\r\n" \
              "Neuesten Nachrichten anzeigen -> /n"
        await update.message.reply_text(out)

    async def read_msg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logging.info("Nachricht wurde angefordert von: {} ({}) ".format(update.message.chat.username,
                                                                        update.message.chat.first_name))
        if self.nntp_th.is_alive():
            await update.message.reply_html("<pre>*** Bitte warten bis die Synchronisierung abgeschlossen ist ! ***\r\n"
                                            "* Die Synchronisierung kann unter Umständen einige Minuten dauern.\r\n"
                                            "* FBB ist nun mal keine junge Frau mehr ;-) also hab etwas Geduld,\r\n"
                                            "* du wirst benachrichtigt wenn der Sync abgeschlossen ist.</pre>")

            if not context.job_queue.get_jobs_by_name(str(update.message.chat_id)):
                context.job_queue.run_repeating(self.sync_noty, 5,
                                                chat_id=update.message.chat_id,
                                                name=str(update.message.chat_id),
                                                data=True)
            else:
                context.job_queue.get_jobs_by_name(str(update.message.chat_id))[0].data = True

        else:
            if self.housekeeping_tr:
                self.housekeeping_tr = False
            tmp = update.message.text.replace('/R_', '').split('_')
            msg_ind = tmp[1].encode()
            grp_ind = list(self.nntp.group_index.keys())[int(tmp[0])]
            msg = self.nntp.get_msg((grp_ind, msg_ind))
            if msg:
                msg = msg.replace('<', '«').replace('>', '»')
                msg = list(self.format_telegram_msg_len(msg))
                for part in msg:
                    await update.message.reply_html('<pre>{}</pre>'.format(part))
                await self.footer(update, context)
            else:
                logging.error("TgBOT read_msg")
                await update.message.reply_html("<pre>*** Error !! Konnte Nachricht nicht abrufen. ***</pre>")

    async def list_headers(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        h_id = int(update.message.text.replace('/T_', ''))
        msg = list(self.format_telegram_msg_len(self.format_nntp_header(h_id)))
        for part in msg:
            await update.message.reply_html(part)
        await self.footer(update, context)

    async def list_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_message.chat_id
        logging.info("Themen Liste angefordert von: {} ({}) ".format(update.message.chat.username,
                                                                     update.message.chat.first_name))
        if update.message.chat.username not in USER.keys():
            USER[update.message.chat.username] = update.message.chat.first_name
        for k in USER.keys():
            print("{} - {}".format(k, USER[k]))
        if self.housekeeping_check():
            if not context.job_queue.get_jobs_by_name(str(chat_id)):
                context.job_queue.run_repeating(self.sync_noty, 5, chat_id=chat_id, name=str(chat_id),
                                                data=True)
            await update.message.reply_html(HOUSEKEEPING_MSG)
        else:
            out = self.format_nntp_groups()
            context.job_queue.run_once(self.sync_fbb_man, 0.5, chat_id=chat_id, name=str(chat_id))
            await update.message.reply_html(out)
            await self.footer(update, context)

    async def list_new_msg(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_message.chat_id
        logging.info("Neue MSG Liste angefordert von: {} ({}) ".format(update.message.chat.username,
                                                                       update.message.chat.first_name))
        if update.message.chat.username not in USER.keys():
            USER[update.message.chat.username] = update.message.chat.first_name
        for k in USER.keys():
            print("{} - {}".format(k, USER[k]))
        if self.housekeeping_check():
            if not context.job_queue.get_jobs_by_name(str(chat_id)):
                context.job_queue.run_repeating(self.sync_noty, 5, chat_id=chat_id, name=str(chat_id),
                                                data=True)
            await update.message.reply_html(HOUSEKEEPING_MSG)
        else:
            out = self.format_nntp_new_msg()
            context.job_queue.run_once(self.sync_fbb_man, 0.3, chat_id=chat_id, name=str(chat_id))
            await update.message.reply_html(out)
            await self.footer(update, context)

    def format_telegram_msg_len(self, str_in: str):
        ret = []
        while len(str_in) > self.max_msg_len:
            ind = str_in[:self.max_msg_len].rfind('\r\n')
            ret.append(str_in[:ind])
            str_in = str_in[ind:]
        ret.append(str_in)
        return ret

    def format_headline(self, headline):
        if type(headline) != str:
            headline = headline.decode('UTF-8')
        # ret = "┖─ Cmd ──┬── Von ───────────┬── Datum ─┬── Betreff ───────────────────┚\r\n"
        """
        ret = "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\r\n" \
              "┃"
        """
        ret = "+---------------------------------------------------------------------+\r\n" \
              "|"
        n = int((71 - 4 - len(headline)) / 2)
        for st in range(n):
            ret += " "
        ret += " {} ".format(headline)
        for st in range(n):
            ret += " "
        if not len(headline) & 1:
            ret += " "
        return "<code>{}|</code>\r\n".format(ret)

    def format_nntp_header(self, grp_id: int):
        grp = list(self.nntp.group_index.keys())[grp_id]
        group = dict(self.nntp.group_index[grp][1])
        if not group:
            return "<code>*** Hier sind keine Nachrichten vorhanden ... ***</code>\r\n"
        ret = self.format_headline(grp)
        # ret += "<code>** Cmd *** Von ************** Datum **** Betreff **********************</code>\r\n"
        # ret += "<code>┖─ Cmd ──┬── Von ───────────┬── Datum ─┬── Betreff ───────────────────┚</code>\r\n"
        ret += "<code>+- Cmd --+-- Von -----------+-- Datum -+-- Betreff -------------------+</code>\r\n"
        key_rev = list(group.keys())
        key_rev.reverse()
        for msg_id in key_rev:
            date = group[msg_id]['Date'][5:-15]
            date = datetime.datetime.strptime(date,  '%d %b %Y')
            date = date.strftime('%d/%m/%y')
            ret += "/R{}_{}<code>| {} | {} | {}</code>\r\n".format(
                str("%02d" % int(grp_id)),
                str("%04d" % int(msg_id)).ljust(4),
                group[msg_id]['From'][:16].replace('<', '').replace('>', '').ljust(16),
                # group[msg_id]['Newsgroups'].ljust(10),
                date.ljust(7),
                group[msg_id]['Subject'][:30].replace('<', '').replace('>', '')
            )
        return ret

    def format_nntp_groups(self):
        groups = list(self.nntp.group_index.keys())
        groups.sort()
        # groups = list(groups.sort())
        ret = "<code>* Cmd ** Thema ***** Nachrichten * neuste Nachricht  *</code>\r\n"
        for key in groups:
            date = ""
            if int(self.nntp.group_index[key][0][0]):
                if self.nntp.group_index[key][1][self.nntp.group_index[key][0][2]]:
                    date = self.nntp.group_index[key][1][self.nntp.group_index[key][0][2]]['Date'][5:-9]
                    # date = datetime.datetime.strptime(date,  '%d %b %Y')
                    # date = date.strftime('%d/%m/%y')
            ret += " /T_{}<code>|  {}{}{}</code>\r\n".format(
                str("%02d" % list(self.nntp.group_index.keys()).index(key)).ljust(5),
                key.decode('UTF-8').ljust(16),
                str(int(self.nntp.group_index[key][0][0])).ljust(10),
                date)
        return ret

    def format_nntp_new_msg(self):
        LISTEN_LEN = 100

        groups = list(self.nntp.group_index.keys())
        ret = self.format_headline("Neuesten Nachrichten")
        # ret += "<code>** Cmd *** Von ************** Datum **** Betreff **********************</code>\r\n"
        ret += "<code>+- Cmd --+-- Von -----------+-- Datum -+-- Betreff -------------------+</code>\r\n"
        msg_dict = dict(self.sort_msg_dict())

        for el in list(msg_dict.keys())[:min(LISTEN_LEN, len(list(msg_dict.keys()))) - 1]:
            grp_index = groups[int(msg_dict[el][:2])]
            msg_index = str(int(msg_dict[el][3:])).encode()
            head = self.nntp.group_index[grp_index][1][msg_index]
            ret += " /R_{}<code>| {} | {} | {}</code>\r\n".format(
                msg_dict[el],
                head['From'][:16].replace('<', '').replace('>', '').ljust(16),
                el.strftime('%d/%m/%y').ljust(7),
                # group[msg_id]['Newsgroups'].ljust(10),
                head['Subject'][:30].replace('<', '').replace('>', '')
            )
        return ret

    def all_headers2dict(self):
        ret = {}
        gp_index = 0
        for gp in list(self.nntp.group_index.keys()):
            for msg in list(self.nntp.group_index[gp][1].keys()):
                msg_id = str("%02d" % gp_index) + "_" + str("%04d" % int(msg))
                ret[msg_id] = self.nntp.group_index[gp][1][msg]
            gp_index += 1
        return ret

    def sort_msg_dict(self):
        msg_dict = self.all_headers2dict()
        tmp = {}
        for msg_id in msg_dict.keys():
            # Sun, 06 Nov 2022 23:19:00 +0100
            date = msg_dict[msg_id]['Date'][5:-9]
            date = datetime.datetime.strptime(date, '%d %b %Y %H:%M')
            # date = date.strftime('%d/%m/%y')
            tmp[date] = str(msg_id)
        sort_list = list(tmp.keys())
        sort_list.sort()
        sort_list.reverse()
        ret = {}
        for k in sort_list:
            ret[k] = tmp[k]
        return ret

    async def sync_noty(self, context: ContextTypes.DEFAULT_TYPE):
        if not self.nntp_th.is_alive():
            if self.housekeeping_tr:
                self.housekeeping_tr = False
            text = ""
            update_info = self.nntp.update_Info_new
            if update_info:
                text = "<code>*** Synchronisierung/Housekeeping wurde soeben beendet. ***\r\n" \
                       "* Neue Nachrichten in: {} </code>".format(update_info)
            elif context.job.data:
                text = "<code>*** Synchronisierung/Housekeeping wurde soeben beendet. ***</code>"
            if text:
                await context.bot.send_message(chat_id=context.job.chat_id,
                                               text=text,
                                               parse_mode='HTML')

            job = context.job_queue.get_jobs_by_name(str(context.job.chat_id))
            job[0].schedule_removal()

    async def sync_fbb_man(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Startet FBB-Update als Thread von Hand"""
        job = context.job
        """
        if self.nntp_th.is_alive():
            await context.bot.send_message(job.chat_id,
                                           text="<code>*** Es läuft eine Synchronisierung im Hintergrund... ***</code>",
                                           parse_mode='HTML')
            pass
            """
        if not self.nntp_th.is_alive():
            self.nntp_th = threading.Thread(target=self.nntp.update_group_index)
            self.nntp_th.start()
            """
            await context.bot.send_message(job.chat_id,
                                           text="<code>*** Synchronisierung mit FBB wird im Hintergrund gestartet ***</code>",
                                           parse_mode='HTML')
            """
        # Start Noty
        if not context.job_queue.get_jobs_by_name(str(context.job.chat_id)):
            context.job_queue.run_repeating(self.sync_noty, 5, chat_id=job.chat_id, name=str(job.chat_id), data=False)

    async def sync_fbb_crone(self, context: ContextTypes.DEFAULT_TYPE):
        """Startet FBB-Update als Thread für Crone Job"""
        if not self.nntp_th.is_alive() and self.housekeeping:
            logging.info("Housekeeping: resync beendet !!!")
            self.housekeeping_tr = False
        if not self.nntp_th.is_alive():
            logging.info("Crone Job gestartet: sync_fbb_crone")
            self.nntp_th = threading.Thread(target=self.nntp.update_group_index)
            self.nntp_th.start()

    async def housekeeping(self, context: ContextTypes.DEFAULT_TYPE):
        logging.info("Housekeeping: wird gestartet !!!")
        while self.nntp_th.is_alive():
            logging.warning("Housekeeping: Warte auf laufenden Sync !!!")
            time.sleep(1)
        self.housekeeping_tr = True
        logging.info("Housekeeping: resync gestartet !!!")
        self.nntp.group_index = {}
        self.nntp_th = threading.Thread(target=self.nntp.update_group_index)
        self.nntp_th.start()
        # logging.info("Housekeeping: resync beendet !!!")

    def housekeeping_check(self):
        if self.housekeeping_tr and self.nntp_th.is_alive():
            return True
        elif self.housekeeping_tr and not self.nntp_th.is_alive():
            self.housekeeping_tr = False
            logging.info("Housekeeping: resync beendet !!!")
            return False
        return False


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s %(levelname)s:%(message)s', level=logging.INFO)
    logging.info("Start")
    bot = TgBot()

