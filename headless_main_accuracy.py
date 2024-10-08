import numpy as np
from datasetProcess import getMech, stackMechs, getBSI
from normalize import normalize_data_122223
from sklearn.neighbors import KDTree
import torch
from vae import VAE
import cv2
from PIL import Image
import os
import bezier
from server import main as server_main
from pathlib import Path
from server import main_8bar as server_main_8bar
from metrics import batch_chamfer_distance, batch_ordered_distance


def decode(mechErrors, bigZ_indices, list_indices, original_indices, param1):
    solutions = []
    ctr = 0
    for count, bigZ_index in enumerate(bigZ_indices):
        BSIpc = getMech(bigZ_index, list_indices, original_indices, param1)
        BSIpc["error"] = mechErrors[count]
        solutions.append(BSIpc)
        ctr += 1
    result = {"version": "1.1.0", "solutions": solutions} # 1.0.0 was using the entire set. 1.1 is using partially 
    return result

def bezier_curve(control_points, num_points=100):
    curve = bezier.Curve(control_points.T, degree=len(control_points) - 1)
    s_vals = np.linspace(0.0, 1.0, num_points)
    return curve.evaluate_multi(s_vals).T

indexPack = stackMechs(['all']) 
kdt = KDTree(np.array(indexPack[0]))

latent_dim = 10

# Initialization of Neural Network 
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
checkpoint_path = f"./weights/lat_{latent_dim}.ckpt"
checkpoint = torch.load(checkpoint_path)
model = VAE(latent_dim)
model.load_state_dict(checkpoint['state_dict'])
model = model.to(device)
model.eval()
knn = 25

def query(img_name):
    global results

    matImg = cv2.imread(img_name, cv2.IMREAD_GRAYSCALE) / 255

    img_name = img_name.split('\\')[1]
    input_string = img_name.split('/')[-1].split('.j')[0] 
    parts = input_string.split()

    # output_dir = os.path.join('./query_outputs/', input_string)

    floats_before = []
    floats_after = []
    letter_string = None
    
    # Iterate over parts to separate floats and the letter string
    for part in parts:
        try:
            # Try to convert part to float
            num = float(part)
            # Add to floats_before if letter_string is not yet found
            if letter_string is None:
                floats_before.append(num)
            else:
                floats_after.append(num)
        except ValueError:
            # If conversion fails, this part is the letter string
            letter_string = part
    
    if len(floats_after) == 6:
            floats_after = floats_after + [0, 0, 1]
    
    floats_before = np.array(floats_before).reshape((-1, 2))
    param1 = np.matrix(floats_after).reshape((3, 3))
    mechType = letter_string.strip()
    ref_points = None

    bsi = getBSI(mechType)

    if mechType.startswith('Type'):
        _, ref_points, success = server_main_8bar(floats_before.tolist(), bsi['B'])
    else:
        _, ref_points, success = server_main(floats_before.tolist(), mechType, bsi['c'].index(1))

    if success: 
        ref_points = np.array(ref_points)
        
        # Get z of the path image
        images = (
            torch.from_numpy(np.array([[matImg]])).float().to(device)
        )

        x = model.encoder(images)
        mean, logvar = x[:, : model.latent_dim], x[:, model.latent_dim :]
        z = model.reparameterize(mean, logvar)
        z = z.cpu().detach().numpy()

        # Search and get mechanism indicies
        # kdt, package = selectTree(mechType) # types of mechanisms desired not implemented as Wei did not make UIs for this function 
        bigZdata, list_indices, original_indices = indexPack
        dist, ind = kdt.query(z.reshape((1, -1)), k=knn)
        mechErrors = dist[0]
        bigZ_indices = ind[0]
        result = decode(mechErrors, bigZ_indices, list_indices, original_indices, param1)
        
        try:
            cdt = 0
            odt = 0
            total_mechs = 0

            ref_points, _, _ = normalize_data_122223(ref_points)
            ref_points_shape = ref_points.shape[0]

            for res in result['solutions']:
                if res['mech'].startswith('Type'):
                    _, p, success = server_main_8bar(res['p'], res['B'])
                else:
                    _, p, success = server_main(res['p'], res['mech'], res['c'].index(1))

                if success:
                    p, _, _ = normalize_data_122223(p)

                    if ref_points_shape != p.shape[0]:
                        if ref_points_shape > p.shape[0]:
                            p = bezier_curve(p, num_points=ref_points_shape)
                        else:
                            ref_points = bezier_curve(ref_points, num_points=p.shape[0])
                            ref_points_shape = p.shape[0]

                    ref_points_copy = np.reshape(ref_points, (1, ref_points_shape, ref_points.shape[1]))
                    p_array = np.array(p)  # Ensure p is a numpy array
                    ref_points_tensor = torch.tensor(ref_points_copy)  # Convert to tensor
                    p_tensor = torch.tensor(p_array)  # Convert to tensor

                    cd = batch_chamfer_distance(ref_points_tensor, p_tensor.unsqueeze(0))
                    od = batch_ordered_distance(ref_points_tensor, p_tensor.unsqueeze(0))

                    cdt += cd.item()
                    odt += od.item()

                    total_mechs += 1

            try:
                results.append((cdt/total_mechs, odt/total_mechs))
            except Exception as e:
                print("An error occurred:", e)
        
        except Exception as e:
            print("An error occurred:", e)

results = []

for images in os.listdir('testing'):
    images = os.path.join('testing', images)
    query(images)

# Initialize sums
sum_first_values = 0
sum_second_values = 0

# Iterate through the array and add the values separately
for value1, value2 in results:
    sum_first_values += value1
    sum_second_values += value2

print(f"Sum of first values: {sum_first_values/len(results)}")
print(f"Sum of second values: {sum_second_values/len(results)}")