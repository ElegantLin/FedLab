import torch
import argparse
import sys
import os

import torchvision
import torchvision.transforms as transforms

sys.path.append("../../../../")

from fedlab.core.client.trainer import SerialTrainer
from fedlab.core.client.scale import ScaleClientManager
from fedlab.core.network import DistNetwork

from fedlab.utils.logger import Logger
from fedlab.utils.aggregator import Aggregators
from fedlab.utils.functional import load_dict

from setting import get_model

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Distbelief training example")

    parser.add_argument("--ip", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=str, default="3002")
    parser.add_argument("--world_size", type=int)
    parser.add_argument("--rank", type=int)

    parser.add_argument("--dataset", type=str, default="mnist")
    parser.add_argument("--partition", type=str, default="iid")

    parser.add_argument("--gpu", type=str, default="0,1,2,3")
    parser.add_argument("--ethernet", type=str, default=None)

    args = parser.parse_args()

    if args.gpu != "-1":
        args.cuda = True
        os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
    else:
        args.cuda = False

    root = "../../../../../datasets/mnist/"
    trainset = torchvision.datasets.MNIST(root=root,
                                          train=True,
                                          download=True,
                                          transform=transforms.ToTensor())

    if args.partition == "noniid":
        data_indices = load_dict("mnist_noniid.pkl")
    elif args.partition == "iid":
        data_indices = load_dict("mnist_iid.pkl")
    else:
        raise ValueError("invalid partition type ", args.partition)

    client_id_list = [
        i for i in range((args.rank - 1) * 10, (args.rank - 1) * 10 + 10)
    ]
    sub_data_indices = {
        idx: data_indices[cid]
        for idx, cid in enumerate(client_id_list)
    }

    model = get_model(args)
    aggregator = Aggregators.fedavg_aggregate

    network = DistNetwork(address=(args.ip, args.port),
                          world_size=args.world_size,
                          rank=args.rank,
                          ethernet=args.ethernet)

    LOGGER = Logger(log_name="client " + str(args.rank))

    trainer = SerialTrainer(model=model,
                            dataset=trainset,
                            data_slices=sub_data_indices,
                            aggregator=aggregator,
                            args={
                                "batch_size": 100,
                                "lr": 0.02,
                                "epochs": 5
                            })

    manager_ = ScaleClientManager(handler=trainer, network=network)

    manager_.run()