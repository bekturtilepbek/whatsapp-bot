// Storage-абстракция (FEATURES.md 2.7): gateway пишет медиа сюда, worker
// читает по тому же ключу (см. libs/integrations/src/integrations/storage
// на Python-стороне). Ключ объекта: bots/{bot_id}/media/{wa_msg_id}.
export interface Storage {
  put(key: string, bytes: Buffer, mimeType: string): Promise<void>;
}
