# YNAB

A CLI tool for performing custom analysis on my You Need A Budget (YNAB) data, as well as viewing the raw data.

## Features

### Functional

- Net Worth report
  - See the total of your open accounts
- Term Distribution report
  - See the distribution of money, by term, in your accounts and categories
  - Terms:
    - short - 0 months - 3 months
    - medium - 3 months - 5 years
    - long - 5+ years
  - Accounts show where the money is right now, categories show where the money is assigned to be spent
  - Hence, the goal should be to align the distribution of categories in the accounts
  - Final column shows, for each term, whether or not the accounts are under/overfunded
- Raw data
  - Accounts
  - Categories

### Non-Functional

- Request Cache
  - Cache API calls to YNAB
  - Configurable TTL
  - YNAB data doesn't change much, so avoid repetitive calls during testing
  - YNAB limits calls to 200 an hour
- Delta Cache
  - Only request data that has changed by storing pointer to last call (known as `last_knowledge_of_server`)
  - Store this using jsonpickle
  - It's not native JSON dumped into the file because of some jsonpickle problems, but only needs unstringing to fix
  - Saves data handling costs for YNAB and reduces network load (minimally obviously)

## TODO

- Revisit jsonpickle issue
  - Not native JSON in the file