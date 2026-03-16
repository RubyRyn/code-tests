import pandas as pd
import os
import re

def load_data(file_1_path, file_2_path):    
    """
    Reads the two dataset snapshots from the data folder.
    """
    print(f"Loading {file_1_path}...")
    before_data = pd.read_csv(file_1_path)
    
    print(f"Loading {file_2_path}...")
    after_data = pd.read_csv(file_2_path)
    
    return before_data, after_data

# Supports both snapshot schemas — maps variant column names to a unified set.
COLUMN_MAPPING = {
    'sku': 'sku',
    'name': 'product_name',
    'quantity': 'quantity',
    'location': 'location',
    'last_counted': 'last_counted',
    'product_name': 'product_name',
    'qty': 'quantity',
    'warehouse': 'location',
    'updated_at': 'last_counted'
}


def parse_mixed_dates(series):
    """Try multiple formats, fill in progressively."""
    formats = [
        '%Y-%m-%d',      # 2024-05-11
        '%m/%d/%Y',      # 01/15/2024
        '%d-%m-%Y',      # 15-01-2024
        '%Y/%m/%d',      # 2024/01/15
    ]

    result = pd.to_datetime(series, errors='coerce')  

    # For anything still NaT, try each format explicitly
    for fmt in formats:
        still_missing = result.isna() & series.notna()
        if not still_missing.any():
            break
        result[still_missing] = pd.to_datetime(series[still_missing], format=fmt, errors='coerce')
    result = result.dt.strftime('%Y-%m-%d')

    return result


def normalize_dtypes(dataframe):
    """Standardize column types."""

    # Strings
    str_cols = ['sku', 'product_name', 'location']
    for col in str_cols:
        if col in dataframe.columns:
            dataframe[col] = dataframe[col].astype(str).str.strip()

    # Numeric columns
    if 'quantity' in dataframe.columns:
        dataframe['quantity'] = pd.to_numeric(dataframe['quantity'], errors='coerce').fillna(0).apply(float)

    # Date
    if 'last_counted' in dataframe.columns:
        dataframe['last_counted'] = parse_mixed_dates(dataframe['last_counted'])

    return dataframe

def validate_clean_sku(df, label='dataset'):
    """Validate and clean SKU column. Returns cleaned df and a list of issues found."""
    issues = []

    # Whitespace and hidden characters
    original = df['sku'].copy()
    df['sku'] = df['sku'].str.strip()
    whitespace_count = (original != df['sku']).sum()
    if whitespace_count > 0:
        issues.append(f"{whitespace_count} SKUs had whitespace issues")

    hidden = df['sku'].str.contains(r'[^\x20-\x7E]', regex=True)
    if hidden.any():
        issues.append(f"{hidden.sum()} SKUs had hidden characters: {df[hidden]['sku'].apply(repr).tolist()}")
        df['sku'] = df['sku'].str.replace(r'[^\x20-\x7E]', '', regex=True)

    # Case consistency
    all_upper = (df['sku'] == df['sku'].str.upper()).all()
    all_lower = (df['sku'] == df['sku'].str.lower()).all()
    if not all_upper and not all_lower:
        issues.append(f"Mixed case detected — normalizing to uppercase")
    df['sku'] = df['sku'].str.upper()

    # Format validation — must be SKU-NNN
    expected_pattern = r'^SKU-\d{3}$'
    valid_format = df['sku'].str.match(expected_pattern)
    if not valid_format.all():
        bad_skus = df[~valid_format]['sku'].tolist()
        issues.append(f"Non-standard format SKUs: {bad_skus}")

        # Fix: extract prefix letters and trailing digits, rebuild as SKU-NNN
        def fix_sku(sku):
            match = re.match(r'^([A-Z]+)-?(\d+)$', sku)
            if match:
                prefix, digits = match.groups()
                return f"{prefix}-{digits.zfill(3)}"
            return sku  # leave unchanged if totally unrecognizable

        df['sku'] = df['sku'].apply(fix_sku)

        fixed = df['sku'].str.match(expected_pattern)
        still_bad = df[~fixed]['sku'].tolist()
        if still_bad:
            issues.append(f"Could not fix these SKUs: {still_bad}")
        else:
            issues.append(f"All SKUs normalized to SKU-NNN format")

    # Length consistency
    lengths = df['sku'].str.len()
    if lengths.nunique() > 1:
        length_counts = lengths.value_counts().to_dict()
        issues.append(f"Inconsistent SKU lengths: {length_counts}")
        common_len = lengths.mode()[0]
        odd_skus = df[lengths != common_len]['sku'].tolist()
        issues.append(f"Non-standard length SKUs: {odd_skus}")

    # Uniqueness
    dupes = df['sku'].duplicated(keep=False)
    if dupes.any():
        dupe_skus = df[dupes]['sku'].unique().tolist()
        issues.append(f"{len(dupe_skus)} duplicate SKUs found: {dupe_skus}")

        # Keep the row with higher quantity
        df = df.sort_values('quantity', ascending=False).drop_duplicates(subset='sku', keep='first').reset_index(drop=True)
        issues.append(f"Duplicates resolved — kept highest quantity for each SKU")

    # Summary
    if issues:
        print(f"\n[{label}] SKU issues found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print(f"\n[{label}] SKUs are clean")

    return df, issues

def generate_sku_product_mapping(df1, df2, label1='Snapshot 1', label2='Snapshot 2'):
    """Build SKU to product_name mapping from both datasets. Flag mismatches."""
    issues = []

    # Clean names before comparing
    df1 = df1.copy()
    df2 = df2.copy()
    # remove the leading and tailing whitespace first.
    df1['product_name'] = df1['product_name'].str.strip()
    df2['product_name'] = df2['product_name'].str.strip()

    # Get SKU-name pairs from both
    map1 = df1.set_index('sku')['product_name'].to_dict()
    map2 = df2.set_index('sku')['product_name'].to_dict()

    # Find mismatches — same SKU, different name
    common_skus = set(map1.keys()) & set(map2.keys())
    mismatches = {
        sku: (map1[sku], map2[sku])
        for sku in common_skus
        if map1[sku] != map2[sku]
    }

    if mismatches:
        issues.append(f"{len(mismatches)} SKU-name mismatches found:")
        for sku, (name1, name2) in mismatches.items():
            issues.append(f"  {sku}: '{name1}' ({label1}) vs '{name2}' ({label2})")

    # Build final mapping — prefer df1's name, fallback to df2
    mapping = {**map2, **map1}

    if issues:
        print("\nSKU-Name mapping issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\nSKU-Name mapping: all consistent")

    return mapping, mismatches


def reconciliation(before, after):
    """
    Perform outer merge on SKU and return a single reconciliation report DataFrame.
    Each row includes before/after quantities, the computed difference, and a change_type label.
    """
    print(f"Before merge, shape of before: {before.shape}")
    print(f"Before merge, shape of after: {after.shape}")
 
    merged = before.merge(after, how="outer", on='sku', suffixes=('_before', '_after'), indicator=True)
    print(f"After merging, shape: {merged.shape}")
 
    def classify_change(row):
        if row['_merge'] == 'left_only':
            return 'removed'
        elif row['_merge'] == 'right_only':
            if row['quantity_after'] == 0:
                return 'out_of_stock'
            return 'added'
        else:
            if row['quantity_after'] == 0:
                return 'out_of_stock'
            elif row['quantity_before'] < row['quantity_after']:
                return 'increased'
            elif row['quantity_before'] > row['quantity_after']:
                return 'decreased'
            else:
                return 'unchanged'
 
    merged['change_type'] = merged.apply(classify_change, axis=1)
 
    # Compute quantity difference (after - before), NaN for added/removed items
    merged['quantity_diff'] = merged['quantity_after'] - merged['quantity_before']

 
    # Consolidate product_name: prefer before, fall back to after
    merged['product_name'] = merged['product_name_before'].fillna(merged['product_name_after'])
 
    # Consolidate location: prefer after (current), fall back to before
    merged['location'] = merged['location_after'].fillna(merged['location_before'])
 
    # Consolidate last_counted: prefer after (most recent), fall back to before
    merged['last_counted'] = merged['last_counted_after'].fillna(merged['last_counted_before'])
 
    # Build the clean report — drop suffixed columns and merge indicator
    report = merged[[
        'sku',
        'product_name',
        'location',
        'quantity_before',
        'quantity_after',
        'quantity_diff',
        'last_counted',
        'change_type',
    ]].copy()
 
    type_order = {'removed': 0, 'decreased': 1, 'increased': 2, 'added': 3, 'unchanged': 4}
    report['_sort'] = report['change_type'].map(type_order)
    report = report.sort_values(['_sort', 'sku']).drop(columns='_sort').reset_index(drop=True)
 
    counts = report['change_type'].value_counts()
    print(f"\nReconciliation summary:")
    for change_type in ['increased', 'decreased', 'removed', 'added', 'unchanged']:
        count = counts.get(change_type, 0)
        print(f"  {change_type}: {count}")
    
 
    return report

if __name__ == "__main__":

    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, 'output')
    data_dir = os.path.join(base_dir, 'data')
    
    file_1_path = os.path.join(data_dir, 'snapshot_1.csv')
    file_2_path = os.path.join(data_dir, 'snapshot_2.csv')
    
    before_data, after_data = load_data(file_1_path, file_2_path)
    
    print("\nSnapshot 1 Data:")
    print(before_data.head())
    
    print("\nSnapshot 2 Data:")
    print(after_data.head())

    before_data = before_data.rename(columns=COLUMN_MAPPING)
    after_data = after_data.rename(columns=COLUMN_MAPPING)


    before_data = normalize_dtypes(before_data)
    after_data = normalize_dtypes(after_data)
    before_data, before_issues = validate_clean_sku(before_data, 'Snapshot 1')
    after_data, after_issues = validate_clean_sku(after_data, 'Snapshot 2')
    product_map, mismatches = generate_sku_product_mapping(before_data, after_data)
    before_data['product_name'] = before_data['sku'].map(product_map)
    after_data['product_name'] = after_data['sku'].map(product_map)

    report = reconciliation(before_data, after_data)

    csv_path = os.path.join(output_dir, 'reconciliation_report.csv')
    json_path = os.path.join(output_dir, 'reconciliation_report.json')
 
    report.to_csv(csv_path, index=False)
    report.to_json(json_path, orient='records', indent=2, date_format='iso')
 
    print(f"\nReport saved to:")
    print(f"  CSV:  {csv_path}")
    print(f"  JSON: {json_path}")