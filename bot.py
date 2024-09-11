import logging
import sqlite3
import os
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, PreCheckoutQueryHandler, filters, ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from collections import defaultdict
import re
from html import escape
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('TOKEN_1')
PAYMENT_PROVIDER_TOKEN = os.getenv('TOKEN_2')

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 3. Input Validation
def validate_input(text):
  # Example: Allow only alphanumeric characters and spaces
  return re.match(r'^[a-zA-Z0-9 ]*$', text) is not None
def validate_string(text):
  # Example: Allow only alphanumeric characters and spaces
  return re.match(r'^[a-zA-Z ]*$', text) is not None

def sanitize_input(input_string):
  """
  Sanitize input by escaping HTML special characters and removing any potential script tags.
  """
  # Escape HTML special characters
  sanitized = escape(input_string)
  # Remove any potential script tags
  sanitized = re.sub(r'<script.*?>.*?</script>', '', sanitized, flags=re.DOTALL | re.IGNORECASE)
  return sanitized

# 4. Rate Limiting
class RateLimiter:
  def __init__(self, max_calls, time_frame):
    self.max_calls = max_calls
    self.time_frame = time_frame
    self.calls = defaultdict(list)

  def is_allowed(self, user_id):
    current_time = datetime.now()
    self.calls[user_id] = [call for call in self.calls[user_id] if call > current_time - self.time_frame]
    if len(self.calls[user_id]) < self.max_calls:
      self.calls[user_id].append(current_time)
      return True
    return False

rate_limiter = RateLimiter(max_calls=40, time_frame=timedelta(minutes=1))

# Main menu keyboard
main_keyboard = ReplyKeyboardMarkup([["Eventi", "I tuoi biglietti"], ["Aggiungi Evento", "Rimuovi Evento"], ["Aggiungi Evento Da Post"]], resize_keyboard=True)
back_button = "Indietro"
cancel_button = "Annulla"
event_keyboard = ReplyKeyboardMarkup([[back_button, cancel_button]], one_time_keyboard=True, resize_keyboard=True)
event_keyboard_NOBACK = ReplyKeyboardMarkup([[cancel_button]], one_time_keyboard=True, resize_keyboard=True)

# Conversation states
TITLE, DATE, DESCRIPTION, PRICE, PHOTO, TRANSFER_OPTION, START_LOCATION, END_LOCATION,TRANSFER_TIME, TRANSFER_PRICE, ADD_FROM_POST, TITLE_FROM_POST= range(12)

mesi_estesi = {
    1: "Gennaio", 2: "Febbraio", 3: "Marzo", 4: "Aprile",
    5: "Maggio", 6: "Giugno", 7: "Luglio", 8: "Agosto",
    9: "Settembre", 10: "Ottobre", 11: "Novembre", 12: "Dicembre"
}

# Ensure the 'event_images' directory exists
if not os.path.exists('event_images'):
  os.makedirs('event_images')

# Database setup
def setup_database():
  conn = sqlite3.connect('event_payments.db')
  c = conn.cursor()
  #c.execute('''DROP TABLE events''')
  #c.execute('''DROP TABLE payments''')
  c.execute('''CREATE TABLE IF NOT EXISTS events
         (id INTEGER PRIMARY KEY, title TEXT, description TEXT, price INTEGER, image_path TEXT,
         start_location TEXT, end_location TEXT, transfer_price INTEGER, transfer_time DATETIME, date DATETIME, active BOOLEAN)''')
  c.execute('''CREATE TABLE IF NOT EXISTS payments
         (id INTEGER PRIMARY KEY, event_id INTEGER, user_id INTEGER, amount INTEGER, 
          timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, is_transfer BOOLEAN,
          transfer_start_location TEXT, time DATETIME, quantity INTEGER)''')
  conn.commit()
  conn.close()

# Database handlers
def add_event(title, description, price, image_path, start_location, end_location, transfer_price, transfer_time, date, active = True):
  conn = sqlite3.connect('event_payments.db')
  c = conn.cursor()
  c.execute("""INSERT INTO events (title, description, price, image_path, start_location, end_location, transfer_price, transfer_time, date, active) 
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, description, price, image_path, start_location, end_location, transfer_price, transfer_time, date, active))
  event_id = c.lastrowid
  conn.commit()
  conn.close()
  return event_id

def rm_event(event_id):
  conn = sqlite3.connect('event_payments.db')
  c = conn.cursor()
  c.execute("""UPDATE events
        SET active = 0
        WHERE id=?""",
        (event_id,))
  conn.commit()
  conn.close()
  return event_id

def add_payment(event_id, user_id, amount, is_transfer, time, quantity, transfer_start_location=None):
  conn = sqlite3.connect('event_payments.db')
  c = conn.cursor()
  c.execute("""INSERT INTO payments (event_id, user_id, amount, is_transfer, time, quantity, transfer_start_location) 
         VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (event_id, user_id, amount, is_transfer, datetime.strptime(time, "%d/%m/%Y %H:%M"), quantity, transfer_start_location))
  payment_id = c.lastrowid
  conn.commit()
  conn.close()
  return payment_id

def get_user_payments(user_id):
  conn = sqlite3.connect('event_payments.db')
  c = conn.cursor()
  c.execute("""SELECT events.title, payments.amount, payments.timestamp, payments.is_transfer, payments.transfer_start_location, payments.time, payments.quantity
         FROM payments 
         JOIN events ON payments.event_id = events.id 
         WHERE payments.user_id = ?""", (user_id,))
  payments = c.fetchall()
  conn.close()
  return payments

def get_all_events():
  conn = sqlite3.connect('event_payments.db')
  c = conn.cursor()
  c.execute("SELECT * FROM events WHERE active = 1")
  events = c.fetchall()
  conn.close()
  return events

def get_event(id : int):
  conn = sqlite3.connect('event_payments.db')
  c = conn.cursor()
  c.execute("SELECT * FROM events WHERE active = 1 and id = ?", (id,))
  event = c.fetchone()[0]
  conn.close()
  return event

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    await update.message.reply_text("Benvenuto! Scegli un'opzione:", reply_markup=main_keyboard)

async def handle_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    events = get_all_events()
    if len(events) == 0:
      await update.message.reply_text("Nessun evento con biglietti disponibili al momento!", reply_markup=main_keyboard)
    else:
      if 'quantity' not in context.user_data:
        context.user_data['quantity'] = {ev[0]: 1 for ev in events}
      chat_id = update.effective_chat.id
      for event in events:
        if event[0] not in context.user_data['quantity']:
          context.user_data['quantity'] = {event[0]: 1}
        quantity = context.user_data['quantity'][event[0]]
        keyboard = [
          [InlineKeyboardButton(f"🎟️ Paga {quantity} bigliett{'o' if quantity == 1 else 'i'} (€{quantity*event[3]/100:.2f})", callback_data=f"pay_{event[0]}")]
        ]
        if  event[7] is not None:  # If transfer_price exists
          keyboard.append([InlineKeyboardButton(f"🚌 Paga {quantity} transfer (€{quantity*event[7]/100:.2f})", callback_data=f"transfer_{event[0]}")])
        
        keyboard.append([
            InlineKeyboardButton("-", callback_data=f"decrease_{event[0]}_{1 if event[7] is not None else 0}_{event[3]}_{event[7] if event[7] is not None else 0}"),
            InlineKeyboardButton("+", callback_data=f"increase_{event[0]}_{1 if event[7] is not None else 0}_{event[3]}_{event[7] if event[7] is not None else 0}")
          ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Parsing della stringa al formato datetime
        date_obj = datetime.strptime(event[9][:-3], "%Y-%m-%d %H:%M")
        # Riformattazione in 'DD-MM-YYYY HH:MM'
        formatted_time = date_obj.strftime("%d/%m/%Y %H:%M ")
        
        if event[7] is None:
          caption=f"{formatted_time[:11]}, ore {formatted_time[11:]}\n\n📍{event[6]}\n\n*{event[1]}*\n\n{event[2]}"
        else:
          transer_data = datetime.strptime(event[8][:-3], "%Y-%m-%d %H:%M")
          mese_esteso = mesi_estesi[transer_data.month]
          caption=f"{formatted_time[:11]}, ore {formatted_time[11:]}\n\n📍{event[6]}\n\n*{event[1]}*\n\n{event[2]}\n\n🚌 Disponibile navetta su prenotazione\n*Quando*: {transer_data.strftime(f"%H:%M, %d {mese_esteso} %y")}\n*Dove*: {event[5]}"
        
        if event[4]:  # If image path exists
          with open(event[4], 'rb') as photo:
            await context.bot.send_photo(
            chat_id=chat_id,
            photo = photo,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
            )
        else:
          await update.message.reply_text(
            f"{event[1]}\n{event[2]}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
          )

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  query = update.callback_query
  data = query.data.split("_")
  action = data[0]
  event_id = int(data[1])
  has_transfer = int(data[2])
  ticket_price = int(data[3])
  if has_transfer:
    transfer_price = int(data[4])
  else:
    transfer_price = 0
  quantity = context.user_data['quantity'][event_id]
  if action == "increase" and quantity == 10 or action == "decrease" and quantity == 1:
    #no modifica
    return
  else:
    if action == "increase":
      context.user_data['quantity'][event_id] = min(10, quantity + 1)
    elif action == "decrease":
      context.user_data['quantity'][event_id] = max(1, quantity - 1)
    quantity = context.user_data['quantity'][event_id]
    if has_transfer:
      keyboard = [
              [InlineKeyboardButton(f"🎟️ Paga {quantity} bigliett{'o' if quantity == 1 else 'i'} (€{quantity*ticket_price/100:.2f})", callback_data=f"pay_{event_id}")],
              [InlineKeyboardButton(f"🚌 Paga {quantity} transfer (€{quantity*transfer_price/100:.2f})", callback_data=f"transfer_{event_id}")],
              [
                InlineKeyboardButton("-", callback_data=f"decrease_{event_id}_1_{ticket_price}_{transfer_price}"),
                InlineKeyboardButton("+", callback_data=f"increase_{event_id}_1_{ticket_price}_{transfer_price}")
              ]
            ]
    else:
      keyboard = [
              [InlineKeyboardButton(f"🎟️ Paga {quantity} bigliett{'o' if quantity == 1 else 'i'} (€{quantity*ticket_price/100:.2f})", callback_data=f"pay_{event_id}")],
              [
                InlineKeyboardButton("-", callback_data=f"decrease_{event_id}_0_{ticket_price}_{transfer_price}"),
                InlineKeyboardButton("+", callback_data=f"increase_{event_id}_0_{ticket_price}_{transfer_price}")
              ]
            ]
    await query.edit_message_reply_markup(reply_markup= InlineKeyboardMarkup(keyboard))

async def handle_my_payments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    user_id = update.effective_user.id
    payments = get_user_payments(user_id)
    current_datetime = datetime.now()
    separator = "\n--------------------\n"
    if payments:
      eventi_futuri = [p for p in payments if datetime.strptime(p[5][:-3], '%Y-%m-%d %H:%M') >= current_datetime - timedelta(days=2)]
      eventi_passati = [p for p in payments if datetime.strptime(p[5][:-3], '%Y-%m-%d %H:%M') < current_datetime - timedelta(days=2)]
      if len(eventi_futuri):
        response = "*📬 I tuoi pagamenti per eventi futuri:*\n"
        response += separator 
        for payment in reversed(eventi_futuri):
          raw_date = datetime.strptime(payment[5][:-3], '%Y-%m-%d %H:%M')
          quantity = int(payment[6])
          mese_esteso = mesi_estesi[raw_date.month]

          response += f"""
🎉 *{payment[0]}*

{'🚌' if payment[3] else '🎟️'} *{quantity}x* {'transfers' if payment[3] else 'tickets'}  
📍 *Data {'Partenza' if payment[3] else 'Evento'}*:\n     {raw_date.strftime(f"%H:%M %d {mese_esteso} %y")}
💳 *Pagato*: €{payment[1]/100:.2f}  
📆 *Data Pagamento*:\n      {payment[2]}
"""
          response += separator 
        response.rstrip(separator)
      if len(eventi_passati):
        if len(eventi_futuri):
          response += "\n*📭 I tuoi pagamenti per eventi passati:*\n"
        else:
          response = "*📭 I tuoi pagamenti per eventi passati:*\n"
        response += separator 
        for payment in reversed(eventi_passati):
          raw_date = datetime.strptime(payment[5][:-3], '%Y-%m-%d %H:%M')
          quantity = int(payment[6])
          formatted_time = raw_date.strftime("%d/%m/%Y %H:%M")
          response += f"""
🎉 *{payment[0]}*

{'🚌' if payment[3] else '🎟️'} *{quantity}x* {'transfers' if payment[3] else 'tickets'}  
📍 *Data {'Partenza' if payment[3] else 'Evento'}*:\n      {raw_date.strftime(f"%H:%M %d {mese_esteso} %y")}
💳 *Pagato*: €{payment[1]/100:.2f}  
📆 *Data Pagamento*:\n      {payment[2]}
"""
          response += separator 
        response.rstrip(separator)
    else:
      response = "Non hai ancora preso biglietti."
    await update.message.reply_text(response,parse_mode=ParseMode.MARKDOWN)

async def handle_add_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == "Aggiungi Evento Da Post":
      await update.message.reply_text("Stai aggiungendo da un post. Qual'è il nome dell'evento?", reply_markup=event_keyboard_NOBACK)
      return TITLE_FROM_POST
    elif update.message.text == "Aggiungi Evento":
      await update.message.reply_text("Aggiungiamo un nuovo evento. Qual'è il nome dell'evento?", reply_markup=event_keyboard_NOBACK)
      return TITLE

async def title_from_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    else:
      sanitized_title = sanitize_input(update.message.text)
      if len(sanitized_title) > 100:  # Limit title length
        await update.message.reply_text("Il titolo è troppo lungo. Per favore, usa meno di 100 caratteri.", reply_markup=event_keyboard)
        return TITLE_FROM_POST
      context.user_data['title'] = update.message.text
      caption = "Perfetto. Ora invia un post da cui prenderò le informazioni sull'evento con questo formato:\n\n"
      caption +="data in formato dd/mm/yyyy hh:mm"
      caption +="\n\n"
      caption +="location / locale"
      caption +="\n\n"
      caption +="descrizione"
      await update.message.reply_text(caption, reply_markup=event_keyboard)
      return ADD_FROM_POST

async def add_from_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
        await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
        return ConversationHandler.END
    elif update.message.text == back_button:
        await update.message.reply_text("Aggiungiamo un nuovo evento. Qual'è il nome dell'evento?", reply_markup=event_keyboard_NOBACK)
        return TITLE_FROM_POST
    elif update.message.text:
      sanitized_post = sanitize_input(update.message.text)
      if len(sanitized_post) > 1024 - 200:  # Limit title length
        await update.message.reply_text("Il post è troppo lungo. Per favore, usa meno caratteri.", reply_markup=event_keyboard)
        return ADD_FROM_POST
      else:
        try:
          caption = [frasi for frasi in sanitized_post.split("\n") if len(frasi)>1]
          '''if datetime.strptime(caption[0].strip(), '%d/%m/%Y %H:%M') < datetime.now():
            await update.message.reply_text("La data indicata è nel passato.\nInvia di nuovo il messaggio con data corretta", reply_markup=event_keyboard)
            return ADD_FROM_POST
          else:'''
          context.user_data['date'] = datetime.strptime(caption[0].strip(), '%d/%m/%Y %H:%M')
          if caption[1][0] == '📍':
              context.user_data['end_location'] = sanitize_input(caption[1][1:])
          else:
              context.user_data['end_location'] = sanitize_input(caption[1])
          context.user_data['description'] = sanitize_input("\n".join(caption[2:]))
          if len(list(context.user_data['description'])) > 1024 - 200:
              await update.message.reply_text("Telegram ha un limite di 1024 caratteri per le descrizioni di immagini.\nLa descrizione che hai mandato potrebbe superare il limite, rimanda il post dell'evento accorciando la descrizione.\n", reply_markup=event_keyboard)
              return ADD_FROM_POST
          else:
              await update.message.reply_text("Qual'è il costo dell'evento? (in centesimi)", reply_markup=event_keyboard)
              return PRICE
        except ValueError:
          await update.message.reply_text(f"Il formato non è corretto, si passa all'inserimento manuale\nOra, inserisci la data e l'ora dell'evento (formato: DD/MM/YYYY HH:MM)\n```Esempio:\n{datetime.now().strftime("%d/%m/%Y %H:%M")}```",  parse_mode=ParseMode.MARKDOWN, reply_markup=event_keyboard)
          return DATE

async def handle_remove_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    events = get_all_events()
    if len(events) == 0:
      await update.message.reply_text("Nessun evento con biglietti disponibili al momento!", reply_markup=main_keyboard)
    else:
      chat_id = update.effective_chat.id
      for event in events:
        keyboard = InlineKeyboardMarkup([
          [InlineKeyboardButton("Rimuovi", callback_data=f"rm_{event[0]}")]
        ])
        if event[4]:  # If image path exists
          with open(event[4], 'rb') as photo:
            await context.bot.send_photo(
              chat_id=chat_id,
              photo = photo,
              caption=f"{event[1]}\n\n{event[2]}",
              reply_markup=keyboard
            )
        else:
          await update.message.reply_text(
            f"{event[1]}\n\n{event[2]}",
            reply_markup=keyboard
          )


async def handle_removal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  query = update.callback_query
  await query.answer()
  
  event_id = int(query.data.split("_")[1])
  rm_event(event_id)

  # Manda un nuovo messaggio
  await context.bot.send_message(chat_id=update.effective_chat.id, text="Event removed")


async def title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    else:
      sanitized_title = sanitize_input(update.message.text)
      if len(sanitized_title) > 100:  # Limit title length
        await update.message.reply_text("Il titolo è troppo lungo. Per favore, usa meno di 100 caratteri.", reply_markup=event_keyboard)
        return TITLE
      else:
        context.user_data['title'] = update.message.text
        await update.message.reply_text(f"Ottimo! Ora, inserisci la data e l'ora dell'evento (formato: DD/MM/YYYY HH:MM):\n```Esempio:\n{datetime.now().strftime("%d/%m/%Y %H:%M")}```",  parse_mode=ParseMode.MARKDOWN,reply_markup=event_keyboard)
        return DATE

async def date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    elif update.message.text == back_button:
      await update.message.reply_text("Aggiungiamo un nuovo evento. Qual'è il nome dell'evento?", reply_markup=event_keyboard_NOBACK)
      return TITLE
    else:
      try:
        '''if datetime.strptime(update.message.text, '%d/%m/%Y %H:%M') < datetime.now():
          await update.message.reply_text("La data indicata è nel passato.\nInvia di nuovo il messaggio con data corretta", reply_markup=event_keyboard)
          return DATE
        else:'''
        context.user_data['date'] = datetime.strptime(sanitize_input(update.message.text), '%d/%m/%Y %H:%M')
        await update.message.reply_text("Qual'è la location / il locale dell'evento?", reply_markup=event_keyboard)
        return END_LOCATION
      except ValueError:
        await update.message.reply_text(f"Il formato non è corretto.```Esempio:\n{datetime.now().strftime("%d/%m/%Y %H:%M")}```",  parse_mode=ParseMode.MARKDOWN, reply_markup=event_keyboard)
        return DATE

async def end_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    elif update.message.text == back_button:
      await update.message.reply_text(f"Ottimo! Ora, inserisci la data e l'ora dell'evento (formato: DD/MM/YYYY HH:MM)\n```Esempio:\n{datetime.now().strftime("%d/%m/%Y %H:%M")}```",  parse_mode=ParseMode.MARKDOWN,reply_markup=event_keyboard)
      return DATE
    else:
      context.user_data['end_location'] = sanitize_input(update.message.text)
      await update.message.reply_text("Ottimo! Ora fornisci una descrizione per l'evento", reply_markup=event_keyboard)
      return DESCRIPTION

async def description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    elif update.message.text == back_button:
      await update.message.reply_text("Qual'è la location / il locale dell'evento?", reply_markup=event_keyboard)
      return END_LOCATION
    else:
      context.user_data['description'] = sanitize_input(update.message.text)
      await update.message.reply_text("Quanto costa un biglietto? (in centesimi)", reply_markup=event_keyboard)
      return PRICE

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    elif update.message.text == back_button:
      await update.message.reply_text("Ottimo! Ora fornisci una descrizione per l'evento", reply_markup=event_keyboard)
      return DESCRIPTION
    else:
      try:
        if int(sanitize_input(update.message.text)) >= 100:
          context.user_data['price'] = int(sanitize_input(update.message.text))
          await update.message.reply_text("Ora manda la locandina dell'evento!", reply_markup=event_keyboard)
          return PHOTO
        else:
          raise ValueError
      except ValueError:
        await update.message.reply_text("Inserisci un numero per il costo del biglietto? (in centesimi)\nValore minimo un euro", reply_markup=event_keyboard)
        return PRICE

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text:
      if update.message.text == cancel_button:
        await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
        return ConversationHandler.END
      elif update.message.text == back_button:
        await update.message.reply_text("Quanto costa un biglietto? (in centesimi)", reply_markup=event_keyboard)
        return PRICE
    elif update.message.photo:
      photo_file = await update.message.photo[-1].get_file()
      file_extension = os.path.splitext(photo_file.file_path)[1]
      file_name = f"event_images/event_{context.user_data['title'].replace(' ', '_')}{file_extension}"
      await photo_file.download_to_drive(file_name)
      context.user_data['image_path'] = file_name
      
      await update.message.reply_text("Vuoi aggiungere una navetta per l'evento? (yes/no)", reply_markup=event_keyboard)
      return TRANSFER_OPTION

async def transfer_option(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    elif update.message.text == back_button:
      await update.message.reply_text("Ora manda la locandina dell'evento!", reply_markup=event_keyboard)
      return PHOTO
    elif update.message.text.lower() == 'yes':
      await update.message.reply_text("Da dove parte il transfer?", reply_markup=event_keyboard)
      return START_LOCATION
    elif update.message.text.lower() == 'no':
      event_id = add_event(
        context.user_data['title'],
        context.user_data['description'],
        context.user_data['price'],
        context.user_data['image_path'],
        None, 
        context.user_data['end_location'],
        None, None,
        context.user_data['date'],
        True
      )
      await update.message.reply_text(f"Event added successfully with ID: {event_id}", reply_markup=main_keyboard)
      return ConversationHandler.END
    else:
      await update.message.reply_text("Non chiaro, rispondi yes/no", reply_markup=event_keyboard)
      return TRANSFER_OPTION

async def start_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    elif update.message.text == back_button:
      await update.message.reply_text("Vuoi aggiungere una navetta per l'evento? (yes/no)", reply_markup=event_keyboard)
      return TRANSFER_OPTION
    else:
      context.user_data['start_location'] = sanitize_input(update.message.text)
      await update.message.reply_text(f"Qual'è l'orario di partenza? (formato: DD/MM/YYYY HH:MM)\n```Esempio:\n{datetime.now().strftime("%d/%m/%Y %H:%M")}```",  parse_mode=ParseMode.MARKDOWN,reply_markup=event_keyboard)
      return TRANSFER_TIME

async def transfer_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    elif update.message.text == back_button:
      await update.message.reply_text("Da dove parte il transfer?", reply_markup=event_keyboard)
      return START_LOCATION
    else:
      try:
        '''
        if datetime.strptime(sanitize_input(update.message.text.strip()), '%d/%m/%Y %H:%M') < datetime.now():
          await update.message.reply_text("La data indicata è nel passato.\nInvia di nuovo il messaggio con data corretta", reply_markup=event_keyboard)
          return ADD_FROM_POST
        else:'''
        context.user_data['transfer_time'] = datetime.strptime(sanitize_input(update.message.text), '%d/%m/%Y %H:%M')
        await update.message.reply_text("Ottimo! Ora fornisci il prezzo del transfer (in centesimi)", reply_markup=event_keyboard)
        return TRANSFER_PRICE
      except ValueError:
        await update.message.reply_text(f"Il formato non è corretto.\n```Esempio:\n{datetime.now().strftime("%d/%m/%Y %H:%M")}```",  parse_mode=ParseMode.MARKDOWN,reply_markup=event_keyboard)
        return TRANSFER_TIME

async def transfer_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    if update.message.text == cancel_button:
      await update.message.reply_text("Conversazione annullata.", reply_markup=main_keyboard)
      return ConversationHandler.END
    elif update.message.text == back_button:
      await update.message.reply_text("Qual'è l'orario di partenza? (formato: DD-MM-YYYY HH:MM)", reply_markup=event_keyboard)
      return TRANSFER_TIME
    else:
      try:
        if int(sanitize_input(update.message.text)) >= 100:
          context.user_data['transfer_price'] = int(sanitize_input(update.message.text))
          event_id = add_event(
            context.user_data['title'],
            context.user_data['description'],
            context.user_data['price'],
            context.user_data['image_path'],
            context.user_data['start_location'],
            context.user_data['end_location'],
            context.user_data['transfer_price'],
            context.user_data['transfer_time'],
            context.user_data['date'],
            True
          )
          await update.message.reply_text(f"Event added successfully with ID: {event_id}", reply_markup=main_keyboard)
          return ConversationHandler.END
        else:
          raise ValueError
      except ValueError:
        await update.message.reply_text("Inserisci un numero valido per il costo del transfer (in centesimi).\nValore minimo un euro", reply_markup=event_keyboard)
        return TRANSFER_PRICE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    await update.message.reply_text("Event creation cancelled.")
    return ConversationHandler.END

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  user = update.effective_user
  if not rate_limiter.is_allowed(user.id):
    await update.message.reply_text("Rate limit exceeded. Please try again later.")
    logger.warning(f"Rate limit exceeded for user {user.id}")
    return
  else:
    query = update.callback_query
    await query.answer()
    
    payment_type, event_id = query.data.split('_')
    event_id = int(event_id)
    quantity = context.user_data['quantity'][event_id]

    conn = sqlite3.connect('event_payments.db')
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    event = c.fetchone()
    conn.close()
    
    if event:
      chat_id = update.effective_chat.id
      title = event[1]
      price = event[3] if payment_type == 'pay' else event[7]
      price = price * quantity
      image_path = event[4]

      # Parsing della stringa al formato datetime
      date_obj = datetime.strptime(event[9][:-3], "%Y-%m-%d %H:%M")

      # Riformattazione in 'DD/MM/YYYY HH:MM'
      formatted_time = date_obj.strftime("%d/%m/%Y %H:%M")
      
      if payment_type == 'pay':
        invoice_payload = f"payment_for_event_{event_id}_{formatted_time}_{quantity}"
        caption = f"{quantity}x 🎟️ bigliett{'i' if quantity > 1 else 'o'}\n{event[1]}\n"
      else:
        invoice_payload = f"payment_for_transfer_{event_id}_{formatted_time}_{quantity}"
        caption = f"{quantity}x 🚌 transfer\n{event[1]} at {event[8]}\n"
      
      await context.bot.send_invoice(
        chat_id, title,  caption, invoice_payload, 
        PAYMENT_PROVIDER_TOKEN, "EUR", [LabeledPrice(title, price)],
        photo_url=f"file://{os.path.abspath(image_path)}" if image_path else None
      )
    else:
      await query.edit_message_text("Event not found")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  query = update.pre_checkout_query
  await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
  payment_info = update.message.successful_payment
  payment_type, event_id, event_date, quantity = payment_info.invoice_payload.split('_')[-4:]
  event_id = int(event_id)
  user_id = update.effective_user.id
  amount = payment_info.total_amount
  quantity = int(quantity)
  
  conn = sqlite3.connect('event_payments.db')
  c = conn.cursor()
  c.execute("SELECT start_location FROM events WHERE id = ?", (event_id,))
  start_location = c.fetchone()[0]
  conn.close()

  is_transfer = payment_type == 'transfer'
  payment_id = add_payment(event_id, user_id, amount, is_transfer, event_date, quantity, start_location if is_transfer else None)
  
  if is_transfer:
    await update.message.reply_text(
      f"Transfer payment of €{amount/100:.2f} was successful!"
    )
  else:
    await update.message.reply_text(
      f"Event payment of €{amount/100:.2f} was successful!"
    )

def main() -> None:
  setup_database()
  application = Application.builder().token(BOT_TOKEN).build()

  conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex("^Aggiungi Evento"), handle_add_event)],
    states={
      TITLE_FROM_POST: [MessageHandler(filters.TEXT & ~filters.COMMAND, title_from_post)],
      ADD_FROM_POST : [MessageHandler(filters.TEXT & ~filters.COMMAND, add_from_post)],
      TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, title)],
      DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date)],
      END_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, end_location)],
      DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description)],
      PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price)],
      PHOTO: [MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, photo)],
      TRANSFER_OPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_option)],
      START_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, start_location)],
      TRANSFER_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_time)],
      TRANSFER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, transfer_price)],
    },
    fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, start)],
  )

  application.add_handler(CommandHandler("start", start))
  application.add_handler(MessageHandler(filters.Regex("^Eventi$"), handle_events))
  application.add_handler(MessageHandler(filters.Regex("^I tuoi biglietti$"), handle_my_payments))
  application.add_handler(conv_handler)
  application.add_handler(MessageHandler(filters.Regex("^Rimuovi Evento$"), handle_remove_event))
  application.add_handler(CallbackQueryHandler(handle_payment, pattern="^(pay|transfer)_"))
  application.add_handler(CallbackQueryHandler(handle_removal, pattern="^rm_"))
  application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
  application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
  application.add_handler(CallbackQueryHandler(button_click, pattern="^(increase|decrease)_"))

  application.run_polling()

if __name__ == '__main__':
  main()