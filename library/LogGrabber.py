# -*- coding: utf-8 -*-

from robot.libraries.BuiltIn import BuiltIn
import zipfile
import os
import shutil
import string

class LogGrabber(object):
    """
    Получение логов подсистем с удаленных серверов. \n
    Библиотека оформлена в качестве [http://robotframework.org/robotframework/latest/RobotFrameworkUserGuide.html#test-libraries-as-listeners|listener],
    в котором реализованы методы start_test и end_test. После подключения библиотеки вся работа с логами может происходить автоматически
    без вызова дополнительных методов. После завершения теста со статусом FAILED будет скачена лишь та часть логов, которая была записана во время его проходжения.\n
    Для работы библиотеки необходимо:\n
    1. Создать переменную server_logs в python [http://robotframework.org/robotframework/latest/RobotFrameworkUserGuide.html#creating-variables-directly|variable file]
    следующего вида:
    | server_logs = {
    |                 "tmpdir": "/tmp/",
    |                 "servers": [
    |                   {
    |                     "hostname": "server.com",
    |                     "port": 22,
    |                     "username": "my_username",
    |                     "password": "my_password_to_ssh",
    |                     "subsystems": [
    |                       {
    |                         "name": "Apache_server",
    |                         "logs": [
    |                           {
    |                             "path_to_log": "/var/log",
    |                             "log_name": "access.log"
    |                           },
    |                           {
    |                             "path_to_log": "/var/log",
    |                             "log_name": "error*.log"
    |                           }
    |                         ]
    |                       }
    |                     ]
    |                   }
    |                 ]
    |               }
    Где:
    - tmpdir - каталог для временных файлов на удаленном сервере
    - hostname - имя хоста удаленного сервера
    - port - порт подключения по ssh
    - username\password - логин\пароль для подключения по ssh
    - name - имя подсистемы, для которой собираются логи
    - path_to_log - путь к логам подсистемы
    - log_name - имя файла лога; могут использоваться wildcards аналогичные тем, что применяются в linux-команде find.
    2. В тестах помимо LogGrabber подключить библиотеки:
    - AdvancedLogging
    - SSHLibrary

    === Ограничения ===
    Логи подсистем должны находится на Linux сервере с возможностью подключения к нему по ssh.

    === Зависимости ===
    | robot framework | http://robotframework.org |
    | AdvancedLogging | http://git.billing.ru/cgit/PS_RF.git/tree/library/AdvancedLogging.py |
    | SSHLibrary | http://robotframework.org/SSHLibrary/latest/SSHLibrary.html |

    """
    ROBOT_LIBRARY_SCOPE = 'GLOBAL'
    
    def __init__(self):
        # загрузка встроенных библиотек
        self.bi=BuiltIn()
        # регистрируем Listener
        self.ROBOT_LIBRARY_LISTENER = self
        self.ROBOT_LISTENER_API_VERSION = 2

        # словарь с подготовленными логами
        self.prepared_logs = dict()

    def _start_test(self, name, attrs):
        self.prepare_logs()

    def _end_test(self, name, attrs):
        if attrs['status'] != 'PASS':
            self.download_logs()

    def _ssh_lib(self):
        return self.bi.get_library_instance("SSHLibrary")

    def _adv_log(self):
        return self.bi.get_library_instance("AdvancedLogging")
        
    def prepare_logs(self):
        """
        Подготовка логов.
        В результате для каждого лога, удовлетворяющего настройке,
        записывается номер послнедней строки.

        """
        
        # Получаем информацию о логах подсистем
        self.logs=self.bi.get_variable_value('${server_logs}')
        # Системный разделитель для платформы запуска тестов
        self.sys_separator=self.bi.get_variable_value('${/}')
        # Разделитель в unix
        self.nix_separator = '/'
        # структура с описанием серверов, подсистем и логов
        self.prepared_logs["servers"] = []
        # перебираем сервера из конфигурации
        for server in self.logs["servers"]:
            processed_server = dict()
            hostname = server["hostname"]
            port = server["port"]
            username = server["username"]
            password = server["password"]
            # заполняем словарь, описывающий обработанный сервер
            processed_server["hostname"] = hostname
            processed_server["port"] = port
            processed_server["username"] = username
            processed_server["password"] = password
            processed_server["subsystems"] = []
            # подключаемся по ssh - alias = host
            self._ssh_lib().open_connection(hostname, hostname, port)
            self._ssh_lib().login(username, password)
            # для каждого сервера обрабатываем набор подсистем
            for subsystem in server["subsystems"]:
                # словарь обработанных подсистем
                processed_subsys = dict()
                processed_subsys["name"] = subsystem["name"]
                # список обработанных логов
                processed_logs = []
                # обрабатываем логи для текущей подсистемы
                for subsys_log in subsystem["logs"]:
                    path_to_log = subsys_log["path_to_log"]
                    log_name_regexp = subsys_log["log_name"]
                    # получаем список лог-файлов по regexp
                    log_name_list_text = self._ssh_lib().execute_command("find {}{}{} -printf '%f\n'".format(path_to_log, self.nix_separator, log_name_regexp), True, True, True)
                    # если список не пуст и код возврата команды 0 (success)
                    if ((len(log_name_list_text[0]) > 0) & (log_name_list_text[2] == 0) ):
                        # формируем массив имен лог-файлов
                        log_name_array = string.split(log_name_list_text[0], '\n')
                        # для каждого файла получаем номер последней строки
                        for log_name in log_name_array:
                            line_number = self._ssh_lib().execute_command("cat {}{}{}  | wc -l".format(path_to_log, self.nix_separator, log_name))
                            processed_logs.append({"path_to_log": path_to_log, "log_name": log_name, "line_number": line_number})
                # проверка для исключения "мусора" processed_subsys
                if (len(processed_logs)>0):
                    processed_subsys["logs"] = processed_logs
                    processed_server["subsystems"].append(processed_subsys)
            # проверка - есть ли для сервера обработанные подсистемы с логами
            if (len(processed_server["subsystems"])>0):
                self.prepared_logs["servers"].append(processed_server)
            # закончили обрабатывать сервер - закрываем соединение
            self._ssh_lib().close_connection()
    
    def download_logs(self):
        """
        Формирование и загрузка логов.
        В результате в директории теста, созданной AdvancedLogging,
        получаем архив с логами [TIMESTAMP]_logs.zip

        """
        timestamp = self.bi.get_time('epoch')
        # базовая директория теста
        base_dir = self._adv_log().Create_Advanced_Logdir()
        # имя результирующего архива с логами
        res_arc_name = os.path.join(base_dir, "{}_logs".format(timestamp))
        # результирующая директория для логов
        logs_dir = os.path.join(base_dir, "logs")
        # временная директория на целевом сервере
        temp_dir = self.logs['tmpdir']
        # обрабатыаем сервера, с подготовленными логами
        for server in self.prepared_logs["servers"]:
            # параметры подключения к серверу
            hostname = server["hostname"]
            port = server["port"]
            username = server["username"]
            password = server["password"]
            # подключаемся по ssh - alias = host
            self._ssh_lib().open_connection(hostname, hostname, port)
            self._ssh_lib().login(username, password)
            # базовая директория для сервера
            server_dir = os.path.join(logs_dir, hostname)
            # обрабатываем подсистемы с подготовленными логами
            for subsystem in server["subsystems"]:
                # структура в которую скачиваются логи [Advanced_Logdir]/logs/<подсистема>/
                subsys_dir = os.path.join(server_dir, subsystem["name"]) #"{}{}{}".format(base_dir, self.sys_separator, subsystem["name"])
                for log in subsystem["logs"]:
                    abs_log_name = "{}{}{}".format(log["path_to_log"], self.nix_separator, log["log_name"])
                    # имя файла содержащего интересующую нас часть, лога
                    cut_log_name = "{}_{}".format(timestamp, log["log_name"])
                    # абсолютный пусть с именем файла (cut_[имя_лога]) - для интересующего нас куска лога
                    cut_abs_log_name = "{}{}{}".format(temp_dir, self.nix_separator, cut_log_name)
                    # текущий номер строки в логе
                    cur_line_number = self._ssh_lib().execute_command("cat {} | wc -l".format(abs_log_name))
                    # проверяем, появились ли строки в логе с момента подготовки логов
                    if (cur_line_number > log["line_number"]):
                        # вырезаем часть лога, начиная с сохраненного номера строки
                        self._ssh_lib().execute_command("tail -n +{} {} > {}".format(log["line_number"], abs_log_name, cut_abs_log_name))
                        # gzip
                        self._ssh_lib().execute_command("gzip {}.gz {}".format(cut_abs_log_name, cut_abs_log_name))
                        # скачиваем файл
                        self._ssh_lib().get_file("{}.gz".format(cut_abs_log_name), "{}{}{}.gz".format(subsys_dir, self.sys_separator, cut_log_name))
                        # удаляем вырезанную чыасть лога и gz-архив этой части
                        self._ssh_lib().execute_command("rm {}".format(cut_abs_log_name))
                        self._ssh_lib().execute_command("rm {}.gz".format(cut_abs_log_name ))
                # если есть результат - упаковываем в единый zip-архив и удаляем папку с логами
                if (os.path.exists(logs_dir)):
                    self._zip(logs_dir, res_arc_name)
                    shutil.rmtree(logs_dir)
            # закончили обрабатывать сервер - закрываем соединение
            self._ssh_lib().close_connection()

    def _zip(self, src, dst):
        """
         Упаковка логов единый zip-архив

        *Args:*\n
        _src_ - директория для упаковки
        _dst_ - имя лога

        """
        zf = zipfile.ZipFile("%s.zip" % (dst), "w", zipfile.ZIP_DEFLATED)
        abs_src = os.path.abspath(src)
        for root, _, files in os.walk(src):
            for filename in files:
                abs_name = os.path.abspath(os.path.join(root, filename))
                arc_name = abs_name[len(abs_src) + 1:]
                zf.write(abs_name, arc_name)
        zf.close()