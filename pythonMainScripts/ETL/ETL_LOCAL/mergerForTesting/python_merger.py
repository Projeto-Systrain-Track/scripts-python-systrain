import pandas as pd
from pathlib import Path

data_folder = Path('')
file_list = list(data_folder.glob('*.csv'))

df = pd.concat([pd.read_csv(f) for f in file_list])
df['data_hora_iso'] = pd.to_datetime(df['data_hora_iso'])
df = df.sort_values(by='data_hora_iso')

df.to_csv('combined_sorted.csv', index=False)