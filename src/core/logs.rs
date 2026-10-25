use std::io::{self, Write};
use tokio::sync::broadcast;
#[derive(Clone)]
pub struct LogWriter(pub broadcast::Sender<String>);
impl Write for LogWriter {
    fn write(&mut self, b: &[u8]) -> io::Result<usize> {
        let _ = self.0.send(String::from_utf8_lossy(b).into_owned());
        io::stderr().write_all(b)?;
        Ok(b.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        io::stderr().flush()
    }
}
impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for LogWriter {
    type Writer = Self;
    fn make_writer(&'a self) -> Self {
        self.clone()
    }
}
