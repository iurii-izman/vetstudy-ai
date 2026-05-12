import React from 'react'
import { EmptyState, LoadingState } from '../../shared/ui/States'
import { FlashcardList, MemoryList, MessageTimeline } from './WorkspaceParts'

export function WorkspaceScreen({ activePanel, setActivePanel, notes, messages, flashcards, onReviewCard, searchResults, onEditNote, loadingTopic }) {
  const panelItems = [
    { id: 'memory', label: 'Memory', count: searchResults.length || notes.length },
    { id: 'dialog', label: 'Dialog', count: messages.length },
    { id: 'cards', label: 'Cards', count: flashcards.length },
  ]

  const memoryItems = searchResults.length ? searchResults : notes

  return (
    <section className="workspace" aria-label="Workspace">
      <div className="segmented-control" role="tablist" aria-label="Workspace panels">
        {panelItems.map((item) => (
          <button key={item.id} aria-selected={activePanel === item.id} className={activePanel === item.id ? 'active' : ''} onClick={() => setActivePanel(item.id)} role="tab" type="button">
            {item.label}<span>{item.count}</span>
          </button>
        ))}
      </div>
      {loadingTopic ? <LoadingState label="Loading topic data..." /> : null}
      {!loadingTopic && activePanel === 'memory' && !memoryItems.length ? <EmptyState title="Нет сохраненных фрагментов" detail="Ответы, заметки и результаты поиска появятся здесь после работы в Telegram." /> : null}
      {!loadingTopic && activePanel === 'dialog' && !messages.length ? <EmptyState title="Нет сообщений" detail="Диалог появится после первого вопроса в выбранном Telegram topic." /> : null}
      {!loadingTopic && activePanel === 'cards' && !flashcards.length ? <EmptyState title="Нет карточек" detail="Создайте карточки кнопкой под ответом бота или командой /cards." /> : null}
      {!loadingTopic && activePanel === 'memory' ? <MemoryList items={memoryItems} onEdit={searchResults.length ? null : onEditNote} sourceLabel="memory" /> : null}
      {!loadingTopic && activePanel === 'dialog' ? <MessageTimeline messages={messages} /> : null}
      {!loadingTopic && activePanel === 'cards' ? <FlashcardList cards={flashcards} onReview={onReviewCard} /> : null}
    </section>
  )
}
