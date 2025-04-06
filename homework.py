import logging
import os
import sys
import time
from datetime import datetime, timedelta
from http import HTTPStatus

import requests
from dotenv import load_dotenv
from telebot import TeleBot

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

DAYS = 30
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
        logger.critical(
            f'Отсутствуют переменные окружения: {", ".join(missing_tokens)}'
        )
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
        logger.debug(f'Бот отправил сообщение "{message}"')
    except Exception as error:
        logger.error(f'Сбой при отправке сообщения: {error}')
        raise TelegramError(
            f'Сбой при отправке сообщения: {error}'
        )


def get_api_answer(timestamp):
    """
    Makes a request to the endpoint of the API service.
    A timestamp is passed to the function as a parameter. If the request is
    successful, it should return an API response, converting it from the JSON
    format to Python data types.
    """
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params=timestamp,
        )
    except requests.exceptions.RequestException as error:
        logger.error(f'Эндпоинт {ENDPOINT} недоступен. Ошибка: {error}')
        raise ConnectionError(
            f'Эндпоинт {ENDPOINT} недоступен. Ошибка: {error}'
        )
    if response.status_code != HTTPStatus.OK:
        logger.error(
            f'Эндпоинт {ENDPOINT} недоступен. Код ответа API: '
            f'{response.status_code}'
        )
        raise APIResponseError(
            f'Эндпоинт {ENDPOINT} недоступен. Код ответа API: '
            f'{response.status_code}'
        )

    try:
        return response.json()
    except ValueError as error:
        logger.error(f'Ошибка преобразования ответа API: {error}')
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
        logger.error('Ответ API не является словарём')
        raise TypeError('Ответ API не является словарём')
    for key in RESPONSE_KEYS:
        if key not in response:
            logger.error(f'В ответе API нет ключа {key}')
            raise KeyError(f'В ответе API нет ключа {key}')
    if not isinstance(response['current_date'], int):
        logger.error('Значение ключа "current_date" не является типом int')
        raise TypeError(
            'Значение ключа "current_date" не является типом int'
        )
    if not isinstance(response['homeworks'], list):
        logger.error('Значение ключа "homeworks" не является типом list')
        raise TypeError(
            'Значение ключа "homeworks" не является типом list'
        )
    if not isinstance(response['homeworks'][0], dict):
        logger.error('Домашняя работа представлена не словарём')
        raise TypeError(
            'Домашняя работа представлена не словарём'
        )
    for key in response['homeworks'][0]:
        if key not in HOMEWORK_KEYS:
            logger.error(f'В объекте домашней работы нет ключа {key}')
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
        logger.error('В ответе API нет ключа "homework_name"')
        raise KeyError('В ответе API нет ключа "homework_name"')
    status = homework['status']
    if status not in HOMEWORK_VERDICTS:
        logger.error('Значение ключа "status" не соответствует ожиданиям')
        raise ValueError(
            'Значение ключа "status" не соответствует ожиданиям'
        )
    verdict = HOMEWORK_VERDICTS[status]

    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    # Проверка токенов check_tokens()
    check_tokens()
    # Создаем объект класса бота
    bot = TeleBot(token=TELEGRAM_TOKEN)
    previous_status = None
    previous_date_updated = None

    while True:
        try:
            response = get_api_answer(PAYLOAD)
            check_response(response)
            homework = response['homeworks'][0]
            homework_status = homework['status']
            date_updated = homework['date_updated']
            message = parse_status(homework)
            if homework_status != previous_status:
                send_message(bot, message)
                previous_status = homework_status
            if previous_date_updated != date_updated:
                date_updated = previous_date_updated

        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            send_message(bot, message)

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
