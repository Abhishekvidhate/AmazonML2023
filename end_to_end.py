import argparse
import glob
import os

import numpy as np
import torch
from lion_pytorch import Lion
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm

from dataset import TextDataset
from model import TransformerRegressor


def train(model, optimizer, train_loader, val_loader, args):
    for epoch in range(args.start_epoch, args.epochs):
        print(f"Epoch: {epoch}")
        train_loss = train_one_epoch(model, optimizer, train_loader, args)
        val_loss, val_mape = val(model, val_loader, args)
        print(
            f"Train Loss: {train_loss} | Val Loss: {val_loss} | Val MAPE: {val_mape} | Best Val MAPE: {args.best_val_mape}"
        )
        args.writer.add_scalar("Epoch/train_loss", train_loss, epoch)
        args.writer.add_scalar("Epoch/val_loss", val_loss, epoch)
        args.writer.add_scalar("Epoch/val MAPE", val_mape, epoch)
        is_best = val_mape < args.best_val_mape
        if is_best:
            args.best_val_mape = val_mape
        state = {
            "epoch": epoch,
            "iter": args.iter,
            "state_dict": model.state_dict(),
            "best_val_mape": args.best_val_mape,
            "optimizer": optimizer.state_dict(),
        }
        if epoch % args.save_every == 0:
            save_checkpoint(state, is_best, args)
            print("Saved model")


def save_checkpoint(state, is_best, args):
    torch.save(state, os.path.join(args.save_dir, f"epoch_{state['epoch']}.pth.tar"))
    last_epoch_path = os.path.join(
        args.save_dir, f"epoch_{state['epoch'] - args.save_every}.pth.tar"
    )

    try:
        os.remove(last_epoch_path)
    except OSError:
        pass

    if is_best:
        past_best = glob.glob(os.path.join(args.save_dir, "model_best_*.pth.tar"))
        past_best = sorted(past_best, key=lambda x: int("".join(filter(str.isdigit, x))))
        if len(past_best) >= 5:
            try:
                os.remove(past_best[0])
            except:
                pass
        torch.save(state, os.path.join(args.save_dir, f"model_best_epoch_{state['epoch']}.pth.tar"))


def train_one_epoch(model, optimizer, train_loader, args):
    model.train()
    loss_fn = torch.nn.MSELoss()
    losses = []
    for i, (x, y) in enumerate(tqdm(train_loader)):
        B = len(y)
        output = model(x, device=args.device)
        loss = loss_fn(output.squeeze(), y.to(args.device))

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        losses.append(loss.item())
        args.iter += B
        if i % args.log_every == 0:
            print(f"Step: {i} | Loss: {loss.item()}")
            args.writer.add_scalar("Iter/train_loss", loss.item(), args.iter)
    return np.mean(losses)


def val(model, val_loader, args):
    model.eval()
    loss_fn = torch.nn.MSELoss()
    losses = []
    mape = 0
    with torch.no_grad():
        for i, (x, y) in enumerate(val_loader):
            y = y.to(args.device)
            output = model(x, device=args.device)
            loss = loss_fn(output.squeeze(), y)
            losses.append(loss.item())
            mape += torch.sum(torch.abs(output - y) / (torch.abs(y) + 1e-8))
    return np.mean(losses), mape.item() / len(val_loader.dataset)


def main(args):
    args.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {args.device}")
    train_set = TextDataset(path="dataset/split_train.csv")
    val_set = TextDataset(path="dataset/split_val.csv")

    print(f"Train set size: {len(train_set)}")
    print(f"Val set size: {len(val_set)}")

    train_loader = DataLoader(
        train_set, batch_size=args.batch_size, num_workers=args.num_workers, shuffle=False
    )
    val_loader = DataLoader(
        val_set, batch_size=args.batch_size, num_workers=args.num_workers, shuffle=False
    )
    print(f"Train loader size: {len(train_loader)}")
    print(f"Val loader size: {len(val_loader)}")

    model = TransformerRegressor(transformer=args.model).to(args.device)
    params = []
    for n, p in model.named_parameters():
        if "transformer" in n:
            params.append({"params": p, "lr": args.lr / 100})
        else:
            params.append({"params": p, "lr": args.lr})

    optimizer = Lion(params, lr=args.lr, use_triton=True)

    args.save_dir = f"checkpoints/{args.run_name}"
    os.makedirs(args.save_dir, exist_ok=True)
    os.makedirs(f"logs/{args.run_name}", exist_ok=True)
    args.writer = SummaryWriter(f"logs/{args.run_name}")

    if args.resume:
        print("Resuming from checkpoint")
        state = torch.load(args.resume)
        model.load_state_dict(state["state_dict"])
        optimizer.load_state_dict(state["optimizer"])
        args.best_val_mape = state["best_val_mape"]
        args.start_epoch = state["epoch"] + 1
        args.iter = state["iter"]
    else:
        args.best_val_mape = np.inf
        args.start_epoch = 0
        args.iter = 0
    train(model, optimizer, train_loader, val_loader, args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # Training
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--log_every", type=int, default=10)
    parser.add_argument("--save_every", type=int, default=1)
    parser.add_argument("--run_name", type=str, default="v0")
    parser.add_argument("--resume", type=str, default="")
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--num_workers", type=int, default=2)

    # Model
    parser.add_argument("--model", type=str, default="bert-base-uncased")

    args = parser.parse_args()
    main(args)
