# Comprehensive Validation Tests

This directory contains comprehensive validation tests for snapshot, diff-to-SQL, and export-schema functionality.

## Test Files

### `test_comprehensive_validation.py`
Comprehensive validation tests covering:
- Snapshot completeness validation
- Round-trip property preservation
- Export-schema round-trip
- Diff accuracy
- SQL generation correctness

### `test_property_preservation.py`
Property-level validation tests:
- Data type preservation
- Constraint preservation
- Default value preservation

### `test_round_trip.py`
Round-trip testing framework tests (existing).

### `schema_validation_utils.py`
Validation utilities:
- `SchemaEquivalenceChecker`: Compares schemas for equivalence
- `PropertyPreservationChecker`: Validates property preservation
- `ValidationResult`: Structured validation results
- `generate_validation_report()`: Human-readable reports

## Running Tests

### Run All Validation Tests
```bash
pytest tests/integration/validation/ -v
```

### Run Specific Test File
```bash
# Comprehensive validation
pytest tests/integration/validation/test_comprehensive_validation.py -v

# Property preservation
pytest tests/integration/validation/test_property_preservation.py -v

# Round-trip tests
pytest tests/integration/validation/test_round_trip.py -v
```

### Run Tests for Specific Database
```bash
# PostgreSQL only
pytest tests/integration/validation/ -k postgresql -v

# Oracle only
pytest tests/integration/validation/ -k oracle -v
```

### Run with Coverage
```bash
pytest tests/integration/validation/ \
  --cov=core/migration/snapshots \
  --cov=core/validation \
  --cov=sql_generator \
  --cov-report=html
```

## Test Requirements

Tests require:
- Database containers (PostgreSQL, MySQL, SQL Server, Oracle, DB2)
- Proper database configuration
- Test data setup

## Expected Results

### Snapshot Completeness Tests
- ✅ All object types captured
- ✅ Snapshot matches live introspection
- ✅ Quality metrics available

### Round-Trip Tests
- ✅ Zero differences after round-trip
- ✅ All properties preserved
- ✅ Generated SQL executes correctly

### Property Preservation Tests
- ✅ All data types preserved
- ✅ All constraints preserved
- ✅ All default values preserved

## Troubleshooting

### Test Failures

1. **Check database connection:**
   ```bash
   # Verify database containers are running
   docker ps
   ```

2. **Check configuration:**
   ```bash
   # Verify config file exists and is valid
   cat dblift.yaml
   ```

3. **Check logs:**
   ```bash
   # Run with debug logging
   pytest tests/integration/validation/ -v -s --log-cli-level=DEBUG
   ```

### Common Issues

1. **Schema not found:**
   - Ensure schema exists in database
   - Check schema name in config

2. **Connection errors:**
   - Verify database is running
   - Check connection credentials

3. **Property differences:**
   - Review detailed difference reports
   - Check normalization logic
   - Verify SQL generation

## Next Steps

1. Run tests to identify issues
2. Review test output and fix failures
3. Add more test cases as needed
4. Integrate into CI/CD pipeline
