import pytest
import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from Reconciliation import (
    load_data,
    parse_mixed_dates,
    normalize_dtypes,
    validate_clean_sku,
    generate_sku_product_mapping,
    reconciliation
)
from unittest.mock import patch

@patch('pandas.read_csv')
def test_load_data(mock_read_csv):
    mock_df1 = pd.DataFrame({'sku': ['SKU-001']})
    mock_df2 = pd.DataFrame({'sku': ['SKU-002']})
    
    mock_read_csv.side_effect = [mock_df1, mock_df2]
    
    df1, df2 = load_data('mock_path_1.csv', 'mock_path_2.csv')
    
    assert mock_read_csv.call_count == 2
    mock_read_csv.assert_any_call('mock_path_1.csv')
    mock_read_csv.assert_any_call('mock_path_2.csv')
    
    assert list(df1.columns) == ['sku']
    assert df1['sku'].iloc[0] == 'SKU-001'
    assert df2['sku'].iloc[0] == 'SKU-002'


def test_parse_mixed_dates():
    dates = pd.Series(['2024-05-11', '01/15/2024', '15-01-2024', '2024/01/15', 'invalid'])
    parsed = parse_mixed_dates(dates)
    
    assert parsed[0] == '2024-05-11'
    assert parsed[1] == '2024-01-15'
    assert parsed[2] == '2024-01-15'
    assert parsed[3] == '2024-01-15'
    assert pd.isna(parsed[4])


def test_normalize_dtypes():
    df = pd.DataFrame({
        'sku': [' SKU-001 ', 'SKU-002'],
        'product_name': [' Apple ', 'Banana '],
        'location': [' WH1 ', 'WH2'],
        'quantity': ['10', 'not_a_number'],
        'last_counted': ['2024-01-01', '01/02/2024']
    })
    norm_df = normalize_dtypes(df.copy())
    
    assert norm_df['sku'].iloc[0] == 'SKU-001'
    assert norm_df['product_name'].iloc[0] == 'Apple'
    assert norm_df['location'].iloc[0] == 'WH1'
    assert norm_df['quantity'].iloc[0] == 10.0
    assert norm_df['quantity'].iloc[1] == 0.0
    assert norm_df['last_counted'].iloc[0] == '2024-01-01'
    assert norm_df['last_counted'].iloc[1] == '2024-01-02'


def test_validate_clean_sku():
    df = pd.DataFrame({
        'sku': [' SKU-001', 'sku-002', 'SKU-3', 'A-4', 'SKU-001'],
        'quantity': [10.0, 20.0, 30.0, 40.0, 50.0]
    })
    clean_df, issues = validate_clean_sku(df.copy(), 'Test Dataset')
    skus = clean_df['sku'].tolist()
    
    assert 'SKU-001' in skus
    assert 'SKU-002' in skus
    assert 'SKU-003' in skus
    assert 'A-004' in skus
    
    # Test deduplication (higher quantity kept)
    sku_001_row = clean_df[clean_df['sku'] == 'SKU-001']
    assert len(sku_001_row) == 1
    assert sku_001_row['quantity'].iloc[0] == 50.0
    assert len(clean_df) == 4


def test_generate_sku_product_mapping():
    df1 = pd.DataFrame({
        'sku': ['SKU-001', 'SKU-002'],
        'product_name': ['Apple', 'Banana Old']
    })
    df2 = pd.DataFrame({
        'sku': ['SKU-002', 'SKU-003'],
        'product_name': ['Banana New', 'Cherry']
    })
    mapping, mismatches = generate_sku_product_mapping(df1, df2)
    
    assert mapping['SKU-001'] == 'Apple'
    assert mapping['SKU-002'] == 'Banana Old'
    assert mapping['SKU-003'] == 'Cherry'
    assert 'SKU-002' in mismatches


def test_reconciliation():
    before = pd.DataFrame({
        'sku': ['SKU-001', 'SKU-002', 'SKU-003'],
        'product_name': ['A', 'B', 'C'],
        'location': ['L1', 'L1', 'L1'],
        'quantity_before': [10.0, 20.0, 30.0],
        'last_counted': ['2024-01-01', '2024-01-01', '2024-01-01']
    })
    before.rename(columns={'quantity_before': 'quantity'}, inplace=True)
    
    after = pd.DataFrame({
        'sku': ['SKU-001', 'SKU-002', 'SKU-004'],
        'product_name': ['A', 'B', 'D'],
        'location': ['L1', 'L2', 'L1'],
        'quantity': [10.0, 15.0, 40.0],
        'last_counted': ['2024-01-02', '2024-01-02', '2024-01-02']
    })
    
    report = reconciliation(before, after)
    
    assert len(report) == 4
    
    sku1 = report[report['sku'] == 'SKU-001'].iloc[0]
    assert sku1['change_type'] == 'unchanged'
    assert sku1['quantity_diff'] == 0.0
    
    sku2 = report[report['sku'] == 'SKU-002'].iloc[0]
    assert sku2['change_type'] == 'decreased'
    assert sku2['quantity_diff'] == -5.0
    assert sku2['location'] == 'L2'
    
    sku3 = report[report['sku'] == 'SKU-003'].iloc[0]
    assert sku3['change_type'] == 'removed'
    assert pd.isna(sku3['quantity_diff'])
    
    sku4 = report[report['sku'] == 'SKU-004'].iloc[0]
    assert sku4['change_type'] == 'added'
    assert pd.isna(sku4['quantity_diff'])


def test_reconciliation_empty_before():
    """All items should be 'added' when before snapshot is empty."""
    before = pd.DataFrame(columns=['sku', 'product_name', 'location', 'quantity', 'last_counted'])
    after = pd.DataFrame({
        'sku': ['SKU-001'],
        'product_name': ['A'],
        'location': ['L1'],
        'quantity': [100.0],
        'last_counted': ['2024-01-15'],
    })
    report = reconciliation(before, after)
    assert len(report) == 1
    assert report['change_type'].iloc[0] == 'added'


def test_reconciliation_empty_after():
    """All items should be 'removed' when after snapshot is empty."""
    before = pd.DataFrame({
        'sku': ['SKU-001'],
        'product_name': ['A'],
        'location': ['L1'],
        'quantity': [100.0],
        'last_counted': ['2024-01-08'],
    })
    after = pd.DataFrame(columns=['sku', 'product_name', 'location', 'quantity', 'last_counted'])
    report = reconciliation(before, after)
    assert len(report) == 1
    assert report['change_type'].iloc[0] == 'removed'


def test_reconciliation_both_empty():
    """Empty report when both snapshots are empty."""
    before = pd.DataFrame(columns=['sku', 'product_name', 'location', 'quantity', 'last_counted'])
    after = pd.DataFrame(columns=['sku', 'product_name', 'location', 'quantity', 'last_counted'])
    report = reconciliation(before, after)
    assert len(report) == 0