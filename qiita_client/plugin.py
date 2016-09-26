# -----------------------------------------------------------------------------
# Copyright (c) 2014--, The Qiita Development Team.
#
# Distributed under the terms of the BSD 3-clause License.
#
# The full license is in the file LICENSE, distributed with this software.
# -----------------------------------------------------------------------------

import traceback
import sys
from os.path import exists, join, dirname, abspath
from os import makedirs
from future import standard_library

from qiita_client import QiitaClient

with standard_library.hooks():
    from configparser import ConfigParser


class QiitaCommand(object):
    """A plugin command

    Parameters
    ----------
    name : str
        The command name
    description : str
        The command description
    function : callable
        The function that executes the command. Should be a callable that
        conforms to the signature:
            `function(qclient, job_id, job_parameters, output_dir)`
        where qclient is an instance of QiitaClient, job_id is a string with
        the job identifier, job_parameters is a dictionary with the parameters
        of the command and output_dir is a string with the output directory
    required_parameters : dict of {str: (str, list of str)}
        The required parameters of the command, keyed by parameter name. The
        values should be a 2-tuple in which the first element is the parameter
        type, and the second parameter is the list of subtypes (if applicable)
    optional_parameters : dict of {str: (str, str)}
        The optional parameters of the command, keyed by parameter name. The
        values should be a 2-tuple in which the first element is the parameter
        name, and the second paramater is the default value
    default_parameter_sets : dict of {str: dict of {str: str}}
        The default parameter sets of the command, keyed by parameter set name.
        The values should be a dictionary in which keys are the parameter names
        and values are the specific value for each parameter

    Raises
    ------
    TypeError
        If `function` is not callable
    ValueError
        If `function` does not accept 4 parameters
    """
    def __init__(self, name, description, function, required_parameters,
                 optional_parameters, default_parameter_sets=None):
        self.name = name
        self.description = description

        # Make sure that `function` is callable
        if not callable(function):
            raise TypeError(
                "Couldn't create command '%s': the provided function is not "
                "callable (type: %s)" % (name, type(function)))

        # `function` will be called with the following Parameters
        # qclient, job_id, job_parameters, output_dir
        # Make sure that `function` can receive 4 parameters
        if function.__code__.co_argcount != 4:
            raise ValueError(
                "Couldn't register command '%s': the provided function does "
                "not accept 4 parameters (number of parameters: %d)"
                % (name, function.__code__.co_argcount))

        self.function = function
        self.required_parameters = required_parameters
        self.optional_parameters = optional_parameters
        self.default_parameter_sets = default_parameter_sets

    def __call__(self, qclient, server_url, job_id, output_dir):
        return self.function(qclient, server_url, job_id, output_dir)


class BaseQiitaPlugin(object):
    def __init__(self, name, version, description, conf_fp=None):
        self.name = name
        self.version = version
        self.decription = description
        self.conf_fp = conf_fp if conf_fp is not None else join(
            dirname(abspath(__file__)), 'support_files', 'config_file.cfg')
        self.task_dict = {}

    def _register_command(self, command):
        """Registers a command in the plugin

        Parameters
        ----------
        command: QiitaCommand
            The command to be added to the plugin
        """
        self.task_dict[command.name] = command

    # def _install(self, qclient):
    #     """Installs the plugin in Qiita"""
    #     for cmd in self.task_dict.values():

    def __call__(self, server_url, job_id, output_dir):
        """Runs the plugin and executed the assigned task

        Parameters
        ----------
        server_url : str
            The url of the server
        job_id : str
            The job id
        output_dir : str
            The output directory

        Raises
        ------
        RuntimeError
            If there is a problem gathering the job information
        """
        # Set up the Qiita Client
        config = ConfigParser()
        with open(self.onf_fp, 'U') as conf_file:
            config.readfp(conf_file)

        qclient = QiitaClient(server_url, config.get('main', 'CLIENT_ID'),
                              config.get('main', 'CLIENT_SECRET'),
                              server_cert=config.get('main', 'SERVER_CERT'))

        if job_id == 'register':
            self._install(qclient)
        else:
            # Request job information. If there is a problem retrieving the job
            # information, the QiitaClient already raises an error
            job_info = qclient.get_job_info(job_id)
            # Starting the heartbeat
            qclient.start_heartbeat(job_id)
            # Execute the given task
            task_name = job_info['command']
            task = self.task_dict[task_name]

            if not exists(output_dir):
                makedirs(output_dir)
            try:
                success, artifacts_info, error_msg = task(
                    qclient, job_id, job_info['parameters'], output_dir)
            except Exception:
                exc_str = repr(traceback.format_exception(*sys.exc_info()))
                error_msg = ("Error executing %s:\n%s" % (task_name, exc_str))
                success = False
                artifacts_info = None
            # The job completed
            qclient.complete_job(job_id, success, error_msg=error_msg,
                                 artifacts_info=artifacts_info)


class QiitaTypePlugin(BaseQiitaPlugin):
    """Represents a Qiita Type Plugin

    Parameters
    ----------
    validate_func : callable
        The function used to validate artifacts
    html_generator_func : callable
        The function used to generate the HTML generator

    Notes
    -----
    Both `validate_func` and `html_generator_func` should be a callable
    that conforms to the signature:
    function(qclient, job_id, job_parameters, output_dir)
    where qclient is an instance of QiitaClient, job_id is a string with
    the job identifier, job_parameters is a dictionary with the parameters
    of the command and output_dir is a string with the output directory
    """
    # List the available commands for a Qiita Type plugin
    _valid_commands = {'Validate', 'Generate HTML summary'}

    def __init__(self, name, version, validate_func, html_generator_func):
        super(QiitaTypePlugin, self).__init__()

        self._register_command('Validate', validate_func)
        self._register_command('Generate HTML summary', html_generator_func)


class QiitaPlugin(BaseQiitaPlugin):
    """Represents a Qiita Plugin"""

    def register_command(self, command_name, function):
        """Registers a command in the plugin

        `function` should be a callable that conforms to the signature:
        function(qclient, job_id, job_parameters, output_dir)
        where qclient is an instance of QiitaClient, job_id is a string with
        the job identifier, job_parameters is a dictionary with the parameters
        of the command and output_dir is a string with the output directory

        Parameters
        ----------
        command_name : str
            The command name
        function : callable
            The function that executed the command

        Raises
        ------
        TypeError
            If `function` is not callable
        ValueError
            If `function` does not accept 4 parameters
        """
        self._register_command(command_name, function)