import threading

import torch.distributed as dist
from torch.multiprocessing import Process

from fedlab_core.utils.logger import logger
from fedlab_core.message_processor import MessageProcessor, MessageCode


class EndTop(Process):
    """Abstract class for server network topology

    If you want to define your own topology agreements, please subclass it.

    Args:
        server_handler: Parameter server backend handler derived from :class:`ParameterServerHandler`
        server_address (tuple): Address of server in form of ``(SERVER_ADDR, SERVER_IP)``
        dist_backend (str or Backend): :attr:`backend` of ``torch.distributed``. Valid values include ``mpi``, ``gloo``,
        and ``nccl``
    """

    def __init__(self, server_handler, server_address, dist_backend):
        self._handler = server_handler
        self.server_address = server_address  # ip:port
        self.dist_backend = dist_backend

        self.msg_processor = MessageProcessor(control_code_size=2, model=self._handler.model)

    def run(self):
        """Process"""
        raise NotImplementedError()

    def activate_clients(self):
        """Activate some of clients to join this FL round"""
        raise NotImplementedError()

    def listen_clients(self):
        """Listen messages from clients"""
        raise NotImplementedError()


class ServerBasicTop(EndTop):
    """Synchronous communication class

    This is the top class in our framework which is mainly responsible for network communication of SERVER!.
    Synchronize with clients following agreements defined in :meth:`run`.

    Args:
        server_handler: Subclass of :class:`ParameterServerHandler`
        server_address (tuple): Address of this server in form of ``(SERVER_ADDR, SERVER_IP)``
        dist_backend (str or Backend): :attr:`backend` of ``torch.distributed``. Valid values include ``mpi``, ``gloo``,
        and ``nccl``. Default: ``"gloo"``
        logger_path (str, optional): path to the log file for this class. Default: ``"server_top.txt"``
        logger_name (str, optional): class name to initialize logger. Default: ``"ServerTop"``

    Raises:
        None
    """

    def __init__(self, server_handler, server_address, dist_backend="gloo", logger_path="server_top.txt",
                 logger_name="ServerTop"):

        super(ServerBasicTop, self).__init__(server_handler=server_handler,
                                             server_address=server_address, dist_backend=dist_backend)

        self._LOGGER = logger(logger_path, logger_name)
        self._LOGGER.info("Server initializes with ip address {}:{} and distributed backend {}".format(
            server_address[0], server_address[1], dist_backend))

        self.global_round = 3  # for test

    def run(self):
        """Process"""
        self._LOGGER.info("Initializing pytorch distributed group")
        self._LOGGER.info("Waiting for connection requests from clients")
        dist.init_process_group(backend=self.dist_backend, init_method='tcp://{}:{}'
                                .format(self.server_address[0], self.server_address[1]),
                                rank=0, world_size=self._handler.client_num_in_total + 1)
        self._LOGGER.info("Connect to clients successfully")

        for round_idx in range(self.global_round):
            self._LOGGER.info(
                "Global FL round {}/{}".format(round_idx+1, self.global_round))

            activate = threading.Thread(target=self.activate_clients)
            listen = threading.Thread(target=self.listen_clients)

            activate.start()
            listen.start()

            activate.join()
            listen.join()

        self.shutdown()

    def activate_clients(self):
        """Activate some of clients to join this FL round"""
        clients_this_round = self._handler.select_clients()
        
        self._LOGGER.info(
            "client id list for this FL round: {}".format(clients_this_round))

        for client_idx in clients_this_round:
            payload = self.msg_processor.pack(control_codes=[MessageCode.ParameterUpdate.value], model=self._handler.model)
            self.msg_processor.send_package(payload=payload, dst=client_idx)

    def listen_clients(self):
        """listen messages from clients"""
        self._handler.train()  # turn train_flag to True
        # server_handler will turn off train_flag
        while self._handler.train_flag:
            package = self.msg_processor.recv_package()
            sender, message_code, s_parameters = self.msg_processor.unpack(payload=package)

            self._handler.on_receive(sender, message_code, s_parameters)

    def shutdown(self):
        for client_idx in range(self._handler.client_num_in_total):
            package = self.msg_processor.pack(control_codes=[MessageCode.Exit.value], model=None)
            self.msg_processor.send_package(payload=package, dst=client_idx+1)