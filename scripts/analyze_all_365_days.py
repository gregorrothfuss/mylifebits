import os, datetime, sqlite3, glob

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/quick-galileo'
ARTIFACT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408'
MEDIA_DIR = os.path.join(ARTIFACT_DIR, 'media_2014_full')

conn_clean = sqlite3.connect(os.path.join(WORKSPACE_DIR, 'timeline_viewer.db'))
c_clean = conn_clean.cursor()

conn_base = sqlite3.connect(os.path.join(WORKSPACE_DIR, 'scratch/original_gms_backup/data/data/com.google.android.gms/databases/odlh-storage.db'))
c_base = conn_base.cursor()

start_date = datetime.date(2014, 1, 1)
all_days = [start_date + datetime.timedelta(days=i) for i in range(365)]

monthly_stats = {}

for dt in all_days:
    day_str = dt.strftime("%Y-%m-%d")
    m_idx = dt.month
    if m_idx not in monthly_stats:
        monthly_stats[m_idx] = {
            'days': 0, 'base_segs': 0, 'clean_segs': 0,
            'visits': 0, 'subway_legs': 0, 'stitched': 0
        }
    monthly_stats[m_idx]['days'] += 1
    
    # Query cleaned
    c_clean.execute(f"SELECT count(*) FROM segments WHERE start_time >= '{day_str}T00:00:00Z' AND start_time <= '{day_str}T23:59:59Z';")
    clean_segs = c_clean.fetchone()[0]
    monthly_stats[m_idx]['clean_segs'] += clean_segs
    
    c_clean.execute(f"SELECT count(*) FROM segments WHERE segment_type='visit' AND start_time >= '{day_str}T00:00:00Z' AND start_time <= '{day_str}T23:59:59Z';")
    visits = c_clean.fetchone()[0]
    monthly_stats[m_idx]['visits'] += visits

    c_clean.execute(f"SELECT count(*) FROM segments WHERE activity_type='in_subway' AND start_time >= '{day_str}T00:00:00Z' AND start_time <= '{day_str}T23:59:59Z';")
    subway = c_clean.fetchone()[0]
    monthly_stats[m_idx]['subway_legs'] += subway

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

print("\n=======================================================")
print(" FULL YEAR 2014 SUMMARY STATISTICS (ALL 12 MONTHS)")
print("=======================================================")
print(f"{'Month':<12} | {'Days':<5} | {'Clean Segs':<11} | {'Visits':<8} | {'Subway Legs':<11}")
print("-" * 60)
for m in range(1, 13):
    st = monthly_stats[m]
    print(f"{MONTH_NAMES[m-1]:<12} | {st['days']:<5} | {st['clean_segs']:<11} | {st['visits']:<8} | {st['subway_legs']:<11}")
print("=======================================================\n")
