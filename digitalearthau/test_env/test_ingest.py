def test_something(test_index):
    ls8_nbar_albers = test_index.products.get_by_name('ls8_nbar_albers')
    expected = ls8_nbar_albers.metadata_type.name
    recorded = ls8_nbar_albers.definition['metadata_type']
    assert expected == recorded
