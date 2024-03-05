# Passabot

Un semplice script che controlla se ci sono appuntamenti disponibili per fare il Passaporto.

## Come funziona

Lo script si connette al sito della Polizia di Stato e controlla una volta al minuto se ci sono appuntamenti disponibili per fare il Passaporto.
Se ci sono appuntamenti disponibili, invia una notifica su Telegram alla chat specificata nelle variabili d'ambiente.

## Che dati fornisce

Quando vengono rilevati degli appuntamenti disponibili, viene inviato un messaggio nella chat identificata dalla variabile `TELEGRAM_DATA_CHAT_ID` con il seguente contenuto:

- **Sede**
- **Slot disponibili** con data, orario e numero di posti disponibili
- **Indirizzo** della sede

<img src="assets/message_example.jpg" alt="Esempio di messaggio" width="300"/>

## Login

Per poter visualizzare i posti disponibili per prenotare il passaporto è necessario effettuare il login sul sito della Polizia di Stato con lo SPID.
Lo script utilizza le credenziali di accesso per effettuare il login (l'unico IDP supportato al momento è **PosteID**) periodicamente.
Una volta immesse le credenziali verrà inviata la notifica per il 2FA sull'app PosteID che dovrà essere approvata entro 1 minuto.

## Utilizzo

1. Installa le dipendenze in un _virtualenv_:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Copia il file `.env.example` in `.env` e modifica le variabili d'ambiente con i tuoi dati
3. Esegui lo script in background (assicurati di essere nel virtualenv):

```bash
python3 main.py & disown
```
