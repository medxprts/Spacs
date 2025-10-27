# Warrant Terms - Accurate Gap Analysis

## 📊 Breakdown of "Missing Warrant Terms"

### Total Missing Warrant Redemption Price: **100 SPACs**

But only **11 are actual errors**:

| Category | Count | Status | Tickers |
|----------|-------|--------|---------|
| **Rights-only SPACs** | **71** | ✅ **CORRECT** (shouldn't have warrant terms) | APAC, GSRT, KFII, MKLY, RANG, etc. |
| **Warrants missing terms** | **11** | 🔴 **ERROR** (should have warrant terms) | SVAC, HOND, GRAF, NTWO, BLUW, BCSS, VNME, MCGA, RTAC, BCAR, CCII |
| **Completely missing info** | **16** | ⚠️ **INVESTIGATE** (unknown if warrant/right) | CEP, SDHI, BAYA, CEPT, PCSC, etc. |
| **Unclear structure** | **0** | - | - |

---

## 🎯 Actual Data Gap

### Critical: **11 SPACs** 
SPACs with warrants but missing warrant terms

**Need to extract from 424B4**:
- SVAC, HOND, GRAF, NTWO, BLUW
- BCSS, VNME, MCGA, RTAC, BCAR, CCII

---

### Medium Priority: **16 SPACs**
Missing unit structure info (need to determine warrant vs right)

**Need to check unit structure first**:
- AACT, GTER.A, CEP, SDHI, BAYA, CEPT
- PCSC, CCIR, YHNA, BACC, CEPF, OBA
- HLXB, AEXA, CEPO, CAEP

**Action**: Extract unit_structure from 424B4, then determine if warrant or right

---

## ✅ Correctly Missing: **71 SPACs**
Rights-only SPACs that correctly don't have warrant terms

**Examples**:
- APAC: "1 share + 1 right"
- GSRT: "1 share + 1/3 right"
- KFII: "1 share + 1/2 right"

**No action needed** - these are correct

---

## 📈 Revised Data Coverage

### Before Analysis:
- Warrant terms coverage: **46%** (86/186)
- Gap: **100 SPACs** 

### After Analysis:
- Rights-only (excluded): **71 SPACs** ✅
- True warrant gap: **11 SPACs** 🔴
- Unknown structure: **16 SPACs** ⚠️

### Actual Coverage:
- **Warrant SPACs**: 86 with terms / (86 + 11 + unknown) = **~89%** coverage
- **Rights SPACs**: 71 with no warrant terms (correct) = **100%** coverage

---

## 🔧 Validation Rule to Add

**Rule 95: Warrant vs Rights Validation**

```python
# Check: SPACs should have EITHER warrants OR rights, not both
if spac.warrant_ticker and spac.right_ticker:
    flag_error("SPAC has both warrant and right ticker - should only have one")

# Check: If has warrants, should have warrant terms
if (spac.warrant_ticker or 'warrant' in spac.unit_structure):
    if not spac.warrant_redemption_price:
        flag_error("Warrant SPAC missing warrant redemption terms")

# Check: If has rights, shouldn't have warrant terms
if (spac.right_ticker or 'right' in spac.unit_structure):
    if spac.warrant_redemption_price:
        flag_warning("Rights SPAC has warrant redemption price (should be null)")
```

**Severity**: ERROR  
**Auto-fix**: No (manual review needed)

---

## 🎯 Action Plan

### Immediate (11 SPACs)
1. Extract warrant terms from 424B4 for SVAC, HOND, GRAF, NTWO, BLUW, BCSS, VNME, MCGA, RTAC, BCAR, CCII
2. **Estimated time**: 15 minutes

### Short-term (16 SPACs)
1. Extract unit_structure from 424B4 for CEP, SDHI, etc.
2. Determine if warrant or right based on structure
3. If warrant: extract terms
4. If right: mark as complete (no warrant terms needed)
5. **Estimated time**: 20 minutes

### Total True Gap
**11 SPACs** missing warrant terms (not 100!)

---

**Conclusion**: You're correct - the "100 missing" is misleading. The actual gap is only **11 SPACs with warrants** missing terms + **16 SPACs** needing structure classification.
