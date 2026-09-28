use pyo3::prelude::*;

const ABI_VERSION: &str = "1.0.0";

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
    module.add_function(wrap_pyfunction!(abi_version, module)?)?;
    module.add_function(wrap_pyfunction!(implementation, module)?)?;
    Ok(())
}
