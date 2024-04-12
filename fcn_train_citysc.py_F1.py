# fcn_train_citysc.py
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision.transforms.functional import to_pil_image
import numpy as np
import seaborn as sns
from PIL import Image
import wandb
from logger import Logger
from utils import apply_palette, f1_score_per_class, format_f1_scores

class SimpleFCN(nn.Module):
    def __init__(self, num_classes):
        super(SimpleFCN, self).__init__()
        
        # Encoder
        self.conv1 = nn.Conv2d(3, 64, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(64, 128, kernel_size=3, padding=1)
        self.conv3 = nn.Conv2d(128, 256, kernel_size=3, padding=1)
        
        # Decoder
        self.upsample1 = nn.ConvTranspose2d(256, 128, kernel_size=2, stride=2)
        self.upsample2 = nn.ConvTranspose2d(128, 64, kernel_size=2, stride=2)
        self.upsample3 = nn.ConvTranspose2d(64, num_classes, kernel_size=2, stride=2)

    def forward(self, x):
        # Encode
        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2) # Pooling to reduce dimensionality
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2)
        x = F.relu(self.conv3(x))
        x = F.max_pool2d(x, 2) 
        
        # Decode
        x = self.upsample1(x)
        x = self.upsample2(x)
        x = self.upsample3(x) # output layer
        
        return x

def train(model, device, train_loader, val_loader, optimizer, num_epochs, my_logger, num_classes):
    # Variables for tracking best validation loss
    best_val_loss = float('inf')
    
    # Move the loss function initialization outside of the loop
    criterion = nn.CrossEntropyLoss()
    
    for epoch in range(1, num_epochs + 1):
        model.train()  # Set model to training mode at the start of each epoch
        total_loss = 0
        
        for batch_idx, (data, target, image_names) in enumerate(train_loader):
            data = data.to(device)
            target = target.to(device)
            optimizer.zero_grad()
            
            # Perform forward pass
            output = model(data)
            
            # Calculate loss
            target = target.long().squeeze(1)  # Ensure target is in the correct shape and type
            loss = criterion(output, target)  # Calculate loss here
            
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item()
        
        avg_loss = total_loss / len(train_loader)
        my_logger.log({"epoch": epoch, "Train Loss": avg_loss})
        print(f"Epoch: {epoch}, Avg Loss: {avg_loss}")

        # Perform validation and calculate validation loss
        if val_loader is not None:
            val_loss, avgF1_perclass = perform_validation(model, val_loader, device, num_classes)
            formatted_f1_scores = format_f1_scores(avgF1_perclass)

            my_logger.log({
                "epoch": epoch, 
                "Val Loss": val_loss,
                "Avg F1 Score Per Class": formatted_f1_scores
                })
            print(f"Epoch: {epoch}, Val Loss: {val_loss}")
            print("F1 Scores:\n", formatted_f1_scores)

            if val_loss < best_val_loss:
                # Assuming log_model_artifact correctly handles saving the model and logging to wandb
                my_logger.log_model_artifact(model, f"Best_Model_epoch_{epoch}", {
                   "val_loss": val_loss,
                   "F1_Score_Summary": np.mean(avgF1_perclass),  # Log a summary statistic for simplicity
                   "epoch": epoch
                })
                best_val_loss = val_loss
                
        # Log sample images at the end of each epoch
        # Use a small batch from either train_loader or val_loader
        model.eval()
        with torch.no_grad():
            for data, target, image_names in val_loader:
                data, target = data.to(device), target.to(device)
                output = model(data)
                break  # Use only the first batch for logging
                
        sample_logs = get_sample_images(data, target, output, image_names[0])
        my_logger.log(sample_logs)
        model.train()  # Set model back to training mode for the next epoch
      
def perform_validation(model, val_loader, device, num_classes):
    model.eval()  # Set the model to evaluation mode
    total_val_loss = 0.0
    criterion = nn.CrossEntropyLoss()  # Define the loss function
    f1_scores_list = [] 

    with torch.no_grad():  # Disable gradient computation for validation
        for data, target, _ in val_loader:  # Ignore image names during validation
            data, target = data.to(device), target.to(device)
            target = target.long().squeeze(1)  # Ensure target is in the correct shape and type
            output = model(data)
            loss = criterion(output, target)
            total_val_loss += loss.item()  # Accumulate the total validation loss

            # Calculate F1 score
            pred = torch.argmax(output, dim=1).cpu().numpy()
            target = target.cpu().numpy()
            _, f1_scores = f1_score_per_class(target, pred, num_classes)
            f1_scores_list.append(f1_scores)

    avg_val_loss = total_val_loss / len(val_loader)  # Calculate the average validation loss
    avg_f1_scores_per_class = np.mean(f1_scores_list, axis=0)  # Calculate the average F1 score for each class
    
    print(f'Average F1 Scores Per Class: {avg_f1_scores_per_class}')

    model.train()  # Set the model back to training mode
    return avg_val_loss, avg_f1_scores_per_class

def get_sample_images(data, target, output, image_name):
    # Convert data, target, output to images, and log them
    pred = torch.argmax(output, dim=1)[0].cpu().numpy()
    true_mask = target[0].cpu().numpy()
    pred_colored = apply_palette(pred)  # Your function to colorize masks
    true_mask_colored = apply_palette(true_mask)
    input_image = to_pil_image(data[0])
    return {
        f"Sample - {image_name}": [wandb.Image(input_image, caption="Input"),
                                   wandb.Image(pred_colored, caption="Prediction"),
                                   wandb.Image(true_mask_colored, caption="True Mask")]
    }





