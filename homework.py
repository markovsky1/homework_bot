import logging
import os
import sys
import time
from datetime import datetime, timedelta
from http import HTTPStatus

import requests
from dotenv import load_dotenv
from telebot import TeleBot
from telebot.apihelper import ApiException

from exceptions import MissingTokenError, TelegramError, APIResponseError


load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TOKENS = {
    'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
    'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
    'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
}

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

DAYS = 14
now = datetime.now()
timestamp = int((now - timedelta(days=DAYS)).timestamp())
PAYLOAD = {'from_date': timestamp}

RESPONSE_KEYS = ['current_date', 'homeworks']
HOMEWORK_KEYS = [
    'date_updated',
    'homework_name',
    'id',
    'lesson_name',
    'reviewer_comment',
    'status',
]


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    '%(asctime)s, %(levelname)s, %(message)s'
)


def check_tokens():
    """
    Checking required variables.

    Checks the availability of environment variables that are necessary for
    the program to work. If at least one environment variable is missing,
    there is no point in continuing the bot's work.
    """
    TOKENS = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }
    missing_tokens = [key for key, value in TOKENS.items() if not value]
    if missing_tokens:
        raise MissingTokenError(
            f'Отсутствуют переменные окружения: {", ".join(missing_tokens)}'
        )
    return True


def send_message(bot, message):
    """
    Sends messages to the Telegram chat.
    Defined by the environment variable TELEGRAM_CHAT_ID. Accepts two
    parameters as input: an instance of the TeleBot class and a string
    with the message text.
    """
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except (ApiException, requests.RequestException) as error:
        raise TelegramError(
            f'Сбой при отправке сообщения: {error}'
        )
    logger.debug(f'Бот отправил сообщение "{message}"')
    return True


def get_api_answer(timestamp):
    """
    Makes a request to the endpoint of the API service.
    A timestamp is passed to the function as a parameter. If the request is
    successful, it should return an API response, converting it from the JSON
    format to Python data types.
    """
    params = {
        'url': ENDPOINT,
        'headers': HEADERS,
        'params': timestamp
    }
    try:
        response = requests.get(**params)
    except requests.exceptions.RequestException as error:
        raise ConnectionError(
            f'Ошибка запроса к {ENDPOINT}. '
            f'Параметры: {params}. Ошибка: {error}'
        )
    if response.status_code != HTTPStatus.OK:
        raise APIResponseError(
            f'Эндпоинт {ENDPOINT} недоступен. Код ответа API: '
            f'{response.status_code}'
            f'Параметры: {params}'
        )

    try:
        return response.json()
    except ValueError as error:
        raise ValueError(
            f'Ошибка преобразования ответа API: {error}'
        )


def check_response(response):
    """
    Checks the API response for compliance with the documentation.
    As a parameter, the function receives an API response converted
    to Python data types.
    """
    if not isinstance(response, dict):
        raise TypeError(
            f'Ответ API не является словарём. Получен тип:{type(response)}'
        )
    for key in RESPONSE_KEYS:
        if key not in response:
            raise KeyError(f'В ответе API нет ключа {key}')
    if not isinstance(response['current_date'], int):
        raise TypeError(
            'Значение ключа "current_date" не является типом int'
            f'Значение ключа "current_date": {type(response["current_date"])}'
        )
    if not isinstance(response['homeworks'], list):
        raise TypeError(
            'Значение ключа "homeworks" не является типом list'
            f'Значение ключа "homeworks": {type(response["homeworks"])}'
        )
    if not isinstance(response['homeworks'][0], dict):
        raise TypeError(
            'Домашняя работа не является словарём.'
            f'Получен тип {type(response["homeworks"][0])}'
        )
    for key in response['homeworks'][0]:
        if key not in HOMEWORK_KEYS:
            raise KeyError(
                f'В объекте домашней работы нет ключа {key}'
            )


def parse_status(homework):
    """
    Extracts the status of this work from the information homework.
    The function gets only one item from the list of household chores as a
    parameter. If successful, the function returns a string prepared for
    sending to Telegram containing one of the verdicts of the HOMEWORK_VERDICTS
    dictionary.
    """
    try:
        homework_name = homework['homework_name']
    except KeyError:
        raise KeyError('В ответе API нет ключа "homework_name"')
    status = homework['status']
    if status not in HOMEWORK_VERDICTS:
        raise ValueError(
            'Значение ключа "status" не соответствует ожиданиям'
        )
    verdict = HOMEWORK_VERDICTS[status]

    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    try:
        check_tokens()
    except MissingTokenError as error:
        logger.critical(error, exc_info=True)
        raise sys.exit()

    bot = TeleBot(token=TELEGRAM_TOKEN)
    previous_date_updated = None
    last_error = None

    while True:
        try:
            response = get_api_answer(PAYLOAD)
            check_response(response)
            # test
            if len(response['homeworks']) == 0:
                logging.debug('Нет новых данных о проектах.')
                previous_date_updated = None
                last_error = None
            homework = response['homeworks'][0]
            date_updated = homework['date_updated']
            message = parse_status(homework)
            if date_updated != previous_date_updated:
                send_message(bot, message)
                previous_date_updated = date_updated

        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message, exc_info=True)
            if message != last_error:
                send_message(bot, message)
                last_error = message

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
