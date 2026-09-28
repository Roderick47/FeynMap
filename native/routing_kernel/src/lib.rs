//! S6.6: Native numeric region-routing kernel.
//!
//! Python remains the semantic authority. This extension owns a copy of the
//! prepared numeric index and only returns region indexes and scores.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

const ABI_VERSION: &str = "1.0.0";

fn invalid(message: impl Into<String>) -> PyErr {
    PyValueError::new_err(message.into())
}

/// Validate CSR offsets and the sorted, unique row contract from S6.5.1.
fn validate_rows(
    name: &str,
    offsets: &[u32],
    values: &[u32],
    region_count: usize,
    upper_bound: usize,
) -> PyResult<()> {
    if offsets.len() != region_count + 1 {
        return Err(invalid(format!("{name}: expected region_count + 1 offsets")));
    }
    if offsets.first() != Some(&0) {
        return Err(invalid(format!("{name}: offsets must start at zero")));
    }
    if offsets.last().map(|value| *value as usize) != Some(values.len()) {
        return Err(invalid(format!("{name}: final offset must equal value count")));
    }
    if offsets.windows(2).any(|window| window[0] > window[1]) {
        return Err(invalid(format!("{name}: offsets must be monotonic")));
    }
    for (row_index, window) in offsets.windows(2).enumerate() {
        let row = &values[window[0] as usize..window[1] as usize];
        if row.iter().any(|value| (*value as usize) >= upper_bound) {
            return Err(invalid(format!("{name}: row {row_index} contains out-of-range index")));
        }
        if row.windows(2).any(|pair| pair[0] >= pair[1]) {
            return Err(invalid(format!("{name}: row {row_index} must be sorted and unique")));
        }
    }
    Ok(())
}

fn weighted_intersection(query: &[u32], row: &[u32], idf_by_token: &[f64]) -> f64 {
    // Both lists are strictly increasing. Their intersection is a linear scan.
    let (mut query_position, mut row_position) = (0, 0);
    let mut total = 0.0;
    while query_position < query.len() && row_position < row.len() {
        let query_token = query[query_position];
        let region_token = row[row_position];
        if query_token == region_token {
            total += idf_by_token[query_token as usize];
            query_position += 1;
            row_position += 1;
        } else if query_token < region_token {
            query_position += 1;
        } else {
            row_position += 1;
        }
    }
    total
}

/// An independently owned, read-only numeric copy of a Python RegionIndex.
///
/// PyO3 turns this #[pyclass] into a Python-visible class. No SemanticGraph,
/// Python dictionary, or Python-owned memory is retained by the Rust object.
#[pyclass(module = "_feynmap_native_routing")]
struct NativeRegionIndex {
    region_weights: Vec<f64>,
    idf_by_token: Vec<f64>,
    unknown_token_idf: f64,
    region_term_offsets: Vec<u32>,
    region_term_ids: Vec<u32>,
    path_term_offsets: Vec<u32>,
    path_term_ids: Vec<u32>,
    adjacency_offsets: Vec<u32>,
    adjacency_region_indices: Vec<u32>,
}

#[pymethods]
impl NativeRegionIndex {
    /// The constructor argument order is pinned in RoutingKernelData.
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        region_weights: Vec<f64>,
        idf_by_token: Vec<f64>,
        unknown_token_idf: f64,
        region_term_offsets: Vec<u32>,
        region_term_ids: Vec<u32>,
        path_term_offsets: Vec<u32>,
        path_term_ids: Vec<u32>,
        adjacency_offsets: Vec<u32>,
        adjacency_region_indices: Vec<u32>,
    ) -> PyResult<Self> {
        let region_count = region_weights.len();
        if region_count > u32::MAX as usize {
            return Err(invalid("region_count exceeds the u32 ABI"));
        }
        if idf_by_token.len() > u32::MAX as usize {
            return Err(invalid("token vocabulary exceeds the u32 ABI"));
        }
        if region_weights.iter().any(|value| !value.is_finite() || *value < 0.0) {
            return Err(invalid("region weights must be finite and non-negative"));
        }
        if idf_by_token.iter().any(|value| !value.is_finite() || *value <= 0.0) {
            return Err(invalid("token IDF weights must be finite and positive"));
        }
        if !unknown_token_idf.is_finite() || unknown_token_idf <= 0.0 {
            return Err(invalid("unknown token IDF must be finite and positive"));
        }
        if region_term_ids.len() > u32::MAX as usize
            || path_term_ids.len() > u32::MAX as usize
            || adjacency_region_indices.len() > u32::MAX as usize
        {
            return Err(invalid("CSR values exceed the u32 offset ABI"));
        }

        validate_rows(
            "region terms",
            &region_term_offsets,
            &region_term_ids,
            region_count,
            idf_by_token.len(),
        )?;
        validate_rows(
            "path terms",
            &path_term_offsets,
            &path_term_ids,
            region_count,
            idf_by_token.len(),
        )?;
        validate_rows(
            "adjacency",
            &adjacency_offsets,
            &adjacency_region_indices,
            region_count,
            region_count,
        )?;

        Ok(Self {
            region_weights,
            idf_by_token,
            unknown_token_idf,
            region_term_offsets,
            region_term_ids,
            path_term_offsets,
            path_term_ids,
            adjacency_offsets,
            adjacency_region_indices,
        })
    }

    #[getter]
    fn region_count(&self) -> usize {
        self.region_weights.len()
    }

    /// Read-only native equivalent of the S6.5.1 compact Python kernel.
    ///
    /// Output: (candidate_count, selected region indices, aligned scores).
    #[pyo3(signature = (query_term_ids, unknown_query_term_count, anchor_region_index, limit))]
    fn route(
        &self,
        query_term_ids: Vec<u32>,
        unknown_query_term_count: u32,
        anchor_region_index: Option<u32>,
        limit: u32,
    ) -> PyResult<(usize, Vec<u32>, Vec<f64>)> {
        if limit == 0 {
            return Err(invalid("route limit must be positive"));
        }
        if query_term_ids.windows(2).any(|pair| pair[0] >= pair[1]) {
            return Err(invalid("query term IDs must be sorted and unique"));
        }
        if query_term_ids
            .iter()
            .any(|token| (*token as usize) >= self.idf_by_token.len())
        {
            return Err(invalid("query term ID outside vocabulary"));
        }
        let region_count = self.region_weights.len();
        let anchor = anchor_region_index.map(|value| value as usize);
        if anchor.is_some_and(|value| value >= region_count) {
            return Err(invalid("anchor region index outside region table"));
        }

        let has_query_terms = !query_term_ids.is_empty() || unknown_query_term_count != 0;
        let mut denominator = 1.0;
        if has_query_terms {
            denominator = query_term_ids
                .iter()
                .map(|token| self.idf_by_token[*token as usize])
                .sum();
            denominator += (unknown_query_term_count as f64) * self.unknown_token_idf;
        }

        let neighbors: &[u32] = match anchor {
            Some(region) => {
                let begin = self.adjacency_offsets[region] as usize;
                let end = self.adjacency_offsets[region + 1] as usize;
                &self.adjacency_region_indices[begin..end]
            }
            None => &[],
        };

        // Numerical tie-breaking uses region indexes. Python assigned indexes
        // in lexical region-ID order, so this reproduces its deterministic sort.
        let mut scored: Vec<(f64, u32)> = Vec::new();
        let mut direct_path_scored: Vec<(f64, u32)> = Vec::new();
        let mut score_by_region: Vec<Option<f64>> = vec![None; region_count];
        let mut considered = 0usize;

        for region in 0..region_count {
            let weight = self.region_weights[region];
            if weight < 0.2 && Some(region) != anchor {
                continue;
            }
            considered += 1;

            let term_begin = self.region_term_offsets[region] as usize;
            let term_end = self.region_term_offsets[region + 1] as usize;
            let path_begin = self.path_term_offsets[region] as usize;
            let path_end = self.path_term_offsets[region + 1] as usize;

            let mut lexical = weighted_intersection(
                &query_term_ids,
                &self.region_term_ids[term_begin..term_end],
                &self.idf_by_token,
            );
            let mut path_match = weighted_intersection(
                &query_term_ids,
                &self.path_term_ids[path_begin..path_end],
                &self.idf_by_token,
            );
            if has_query_terms {
                lexical /= denominator;
                path_match /= denominator;
            }

            lexical = (lexical + (1.5 * path_match)) * weight;
            let locality = if Some(region) == anchor {
                2.0
            } else if neighbors.binary_search(&(region as u32)).is_ok() {
                0.10
            } else {
                0.0
            };
            let score = lexical + locality;
            if score > 0.0 {
                scored.push((score, region as u32));
                score_by_region[region] = Some(score);
            }
            if path_match > 0.0 {
                direct_path_scored.push((path_match * weight, region as u32));
            }
        }

        scored.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| a.1.cmp(&b.1)));
        direct_path_scored.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| a.1.cmp(&b.1)));

        // Preserve the Python router's alternating general/direct-path slots.
        let limit = limit as usize;
        let mut selected: Vec<u32> = Vec::with_capacity(limit.min(region_count));
        let mut seen = vec![false; region_count];
        let (mut general_index, mut path_index) = (0, 0);
        while selected.len() < limit
            && (general_index < scored.len() || path_index < direct_path_scored.len())
        {
            if general_index < scored.len() {
                let region_id = scored[general_index].1;
                general_index += 1;
                if !seen[region_id as usize] {
                    seen[region_id as usize] = true;
                    selected.push(region_id);
                    if selected.len() >= limit {
                        break;
                    }
                }
            }
            if path_index < direct_path_scored.len() {
                let region_id = direct_path_scored[path_index].1;
                path_index += 1;
                if !seen[region_id as usize] {
                    seen[region_id as usize] = true;
                    selected.push(region_id);
                }
            }
        }

        if let Some(anchor_region) = anchor_region_index {
            if !seen[anchor_region as usize] {
                selected.insert(0, anchor_region);
                selected.truncate(limit);
            }
            if selected.is_empty() {
                selected.push(anchor_region);
            }
        }

        let selected_scores = selected
            .iter()
            .map(|region_id| {
                score_by_region[*region_id as usize].unwrap_or_else(|| {
                    if Some(*region_id) == anchor_region_index { 2.0 } else { 0.0 }
                })
            })
            .collect();

        Ok((considered, selected, selected_scores))
    }
}

#[pyfunction]
fn abi_version() -> &'static str {
    ABI_VERSION
}

#[pyfunction]
fn implementation() -> &'static str {
    "rust-pyo3"
}

#[pymodule]
fn _feynmap_native_routing(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__abi_version__", ABI_VERSION)?;
    module.add_class::<NativeRegionIndex>()?;
    module.add_function(wrap_pyfunction!(abi_version, module)?)?;
    module.add_function(wrap_pyfunction!(implementation, module)?)?;
    Ok(())
}
