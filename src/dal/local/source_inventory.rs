//! Read-only source snapshots for central documentation. No service HTTP calls.
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
pub struct SourceFile {
    pub path: PathBuf,
    pub text: String,
}
pub struct SourceSnapshot {
    pub files: Vec<SourceFile>,
    pub sha256: String,
}
fn collect(root: &Path, extension: &str, out: &mut Vec<PathBuf>) -> std::io::Result<()> {
    for entry in std::fs::read_dir(root)? {
        let entry = entry?;
        let path = entry.path();
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with('.')
            || matches!(
                name.as_ref(),
                "build" | "dist" | "target" | "tests" | "docs" | "tools" | "__pycache__"
            )
        {
            continue;
        }
        if path.is_dir() {
            collect(&path, extension, out)?
        } else if path.extension().is_some_and(|v| v == extension) {
            out.push(path)
        }
    }
    Ok(())
}
pub fn read(root: &Path, extension: &str) -> std::io::Result<SourceSnapshot> {
    let mut paths = vec![];
    collect(root, extension, &mut paths)?;
    paths.sort();
    let mut hash = Sha256::new();
    let mut files = vec![];
    for path in paths {
        let text = std::fs::read_to_string(&path)?;
        hash.update(
            path.strip_prefix(root)
                .unwrap_or(&path)
                .to_string_lossy()
                .as_bytes(),
        );
        hash.update([0]);
        hash.update(text.as_bytes());
        hash.update([0]);
        files.push(SourceFile { path, text });
    }
    Ok(SourceSnapshot {
        files,
        sha256: format!("{:x}", hash.finalize()),
    })
}
