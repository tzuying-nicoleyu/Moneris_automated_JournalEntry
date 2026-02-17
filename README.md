
# Moneris Sales Summary to NetSuite Journal Entries
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Code style: black](https://img.shields.io/badge/code%20style-black-000000)

This project is designed as a backend and database tool for automated the process of posting sales from POS system to ERP system.
In this project, Moneris POS and NetSuite are used.

---
## Prerequsites:
- Access to Moneris Merchant Direct.
- NetSuite's Admin role.

---
## Setup 
1. Clone the repository and Install dependencies:
```bash
git clone https://github.com/tzuying-nicoleyu/Moneris_automated_JournalEntry.git
cd Moneris_automated_JournalEntry
pip install -r requirements.txt
```
2. File Needed in main project folder: 
- Install a Moneris.db in the main project folder
- Need the moneris_practice_mapping.csv in the main project folder

3. How to run:
step 1. Login to Moneris Portal. (https://www.moneris.com/en/login-portal-hub)
step 2. Open the menu > Go to Reports > Go to'CSV Downloader' page
step 3. Choose "Sales summary by merchant" as Report. Choose the date. Click Csv Download. 
step 4. Please choose a designated folder. Update the download_folder_path in Checkpoint() class in classes.py to this designated folder path.
step 5. In terminal run the following code.
``` bash
python main.py
```
/*Warning*/: The main script process one file at a time. To run multiple files, repeat step 3 - 5. 



