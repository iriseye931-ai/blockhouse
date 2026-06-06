import { useState, useEffect } from 'react'
import type { GraphSelection } from '../types'
import RAGSearch from './RAGSearch'
import AmpInbox from './AmpInbox'
import { TabBar, TAB_LABELS, C } from './panel/Primitives'
import LogsTab from './panel/LogsTab'
import HermesTab from './panel/HermesTab'

type Tab = 'logs' | 'amp' | 'hermes' | 'rag'

export default function MeshPanel({
  focus = null,
  onFocusChange,
}: {
  focus?: GraphSelection | null
  onFocusChange?: (focus: GraphSelection | null) => void
}) {
  const [activeTab, setActiveTab] = useState<Tab>('hermes')

  useEffect(() => {
    if (focus) setActiveTab('hermes')
  }, [focus])

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'linear-gradient(180deg, rgba(14,8,28,0.98), rgba(7,3,14,0.99))' }}>
      <TabBar active={activeTab} onChange={setActiveTab} />
      {activeTab === 'logs' && <LogsTab />}
      {activeTab === 'amp' && <AmpInbox />}
      {activeTab === 'hermes' && <HermesTab focus={focus} onFocusChange={onFocusChange} />}
      {activeTab === 'rag' && (
        <div style={{ flex: 1, padding: '8px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <RAGSearch />
        </div>
      )}
    </div>
  )
}
