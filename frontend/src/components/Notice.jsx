// Inline status message. tone: 'info' | 'partial' | 'empty' | 'error'.
export default function Notice({ tone = 'info', title, children }) {
  return (
    <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {title && <strong>{title} </strong>}
      {children}
    </div>
  )
}
