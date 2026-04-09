/**
 * Data Layer — database, session management, configuration.
 */

export { BridgeDatabase } from "./db.js";
export { MessageDatabase } from "./message-db.js";
export { SessionManager } from "./session.js";
export type { IDatabase, IMessageDatabase, ISessionManager, IConfigProvider } from "./interfaces.js";
