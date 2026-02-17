
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
``` bash
python main.py
```



