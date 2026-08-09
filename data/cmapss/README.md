# NASA C-MAPSS Turbofan Engine Degradation Data

## Download Instructions

Download the dataset from NASA:
1. Go to: https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data
2. Download the ZIP file
3. Extract into this directory

Alternatively, use the download script:
```bash
python download_cmapss.py
```

## Expected Files After Download

```
data/cmapss/
├── train_FD001.txt    (100 engines, 1 fault mode, 1 operating condition)
├── test_FD001.txt
├── RUL_FD001.txt
├── train_FD002.txt    (260 engines, 1 fault mode, 6 operating conditions)
├── test_FD002.txt
├── RUL_FD002.txt
├── train_FD003.txt    (100 engines, 2 fault modes, 1 operating condition)
├── test_FD003.txt
├── RUL_FD003.txt
├── train_FD004.txt    (249 engines, 2 fault modes, 6 operating conditions)
├── test_FD004.txt
└── RUL_FD004.txt
```

## Data Format (26 columns, space-separated)

| Column | Name | Description |
|--------|------|-------------|
| 1 | unit_number | Engine ID (1-100 for FD001) |
| 2 | time_cycles | Flight cycle number |
| 3 | op_setting_1 | Operational setting 1 |
| 4 | op_setting_2 | Operational setting 2 |
| 5 | op_setting_3 | Operational setting 3 |
| 6 | sensor_1 | Fan inlet temperature (Total) |
| 7 | sensor_2 | LPC outlet temperature (Total) |
| 8 | sensor_3 | HPC outlet temperature (Total) |
| 9 | sensor_4 | LPT outlet temperature (Total) |
| 10 | sensor_5 | Fan inlet pressure (Total) |
| 11 | sensor_6 | Bypass-duct pressure (Total) |
| 12 | sensor_7 | HPC outlet pressure (Total) |
| 13 | sensor_8 | Physical fan speed (rpm) |
| 14 | sensor_9 | Physical core speed (rpm) |
| 15 | sensor_10 | Engine pressure ratio |
| 16 | sensor_11 | HPC outlet static pressure |
| 17 | sensor_12 | Ratio fuel flow to Ps30 |
| 18 | sensor_13 | Corrected fan speed (rpm) |
| 19 | sensor_14 | Corrected core speed (rpm) |
| 20 | sensor_15 | Bypass ratio |
| 21 | sensor_16 | Burner fuel-air ratio |
| 22 | sensor_17 | Bleed enthalpy |
| 23 | sensor_18 | Demanded fan speed (rpm) |
| 24 | sensor_19 | Demanded corrected fan speed |
| 25 | sensor_20 | HPT coolant bleed |
| 26 | sensor_21 | LPT coolant bleed |

## Citation

A. Saxena and K. Goebel (2008). "Turbofan Engine Degradation Simulation Data Set",
NASA Ames Prognostics Data Repository, NASA Ames, Moffett Field, CA.
