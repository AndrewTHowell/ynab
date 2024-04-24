# YNAB

A CLI tool for performing custom analysis on your You Need A Budget (YNAB) data, as well as viewing the raw data.

## Usage

To start the CLI, start `ynab.py`:
```
python ynab.py
```

## Config

The tool expects a config json file. The schema for this config can be found in `config_schema.json`

For more information, see the help section:
```
❯ python ynab.py -h
usage: ynab.py [-h] [-c CONFIG_FILE_PATH] [-m {normal,freeze,flush}] [-d]

Script for consuming and processing YNAB data.

options:
  -h, --help            show this help message and exit
  -c CONFIG_FILE_PATH, --config_file_path CONFIG_FILE_PATH
                        The path to the configuration for this script. See schema at `config_schema.json`
  -m {normal,freeze,flush}, --cache_mode {normal,freeze,flush}
                        Choose a cache mode
  -d, --debug           Turn on debug logging
```

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
  - **Note:** for this report to work, all your accounts must have an account note including the substring `<term> Term`
- Rollover Balance report
  - See how much is left over in Needed For Spending Categories currently
  - It answers: when monthly rollover occurs, how much will rollover to next month given the current balances
- Raw data
  - Accounts
  - Categories
  - Redundant Payees (Payees with no associated Transactions which can likely be deleted)

### Non-Functional

- Request Cache
  - Cache API calls to YNAB
  - Configurable TTL
  - YNAB data doesn't change much, so avoid repetitive calls during testing
  - YNAB limits calls to 200 an hour
    - Warning log added in case it gets close to the limit
- Delta Cache
  - Only request data that has changed by storing pointer to last call (known as `last_knowledge_of_server`)
  - Store this using jsonpickle
  - It's not native JSON dumped into the file because of some jsonpickle problems, but only needs unstringing to fix
  - Saves data handling costs for YNAB and reduces network load (minimally obviously)

## TODO

- Revisit jsonpickle issue
  - Non-native JSON in the file
- Pull file paths out and into config