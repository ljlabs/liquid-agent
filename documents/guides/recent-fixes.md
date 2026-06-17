# Recent UI and Database Fixes

## Summary
Fixed 4 major issues to improve the multi-turn conversation experience and data persistence.

## 1. Hide Permission Bubbles After Response
**File**: `ui-components.js`
**Change**: Permission request cards now fade out and hide 1 second after user responds
**Effect**: Cleaner UI, permissions don't clutter the conversation after being resolved

## 2. Separate Messages Per Turn
**File**: `stream-handler.js`
**Change**: Each LLM response now creates a new message element instead of reusing the first one
**Effect**: 
- Thinking tags are properly scoped to each turn
- Each turn's content is visually separated
- Easier to see which tools belong to which turn

## 3. Store Tool Input/Output and Permissions
**Files**: `database.py`, `main.py`
**Changes**:
- Added `permissions` table to track all permission requests and responses
- Columns: session_id, request_id, tool_name, tool_input, approved, always, created_at
- Updated permission endpoint to log every permission decision
**Effect**: Full audit trail of all permission decisions for security and debugging

## 4. Fix Thinking Tags After Reload
**File**: `session-manager.js`
**Change**: When loading messages from database, parse `<thought>` tags and recreate collapsible thinking sections
**Effect**: Thinking sections remain collapsible and properly formatted after page refresh

## Database Schema Changes

### New Table: `permissions`
```sql
CREATE TABLE permissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    request_id  TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    tool_input  TEXT,
    approved    INTEGER NOT NULL,
    always      INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);
```

### Existing Tables (Already Had These Columns)
- `messages.tool_name`: Tool name for tool_use messages
- `messages.tool_id`: Tool call ID
- `messages.tool_input`: JSON string of tool input parameters

## Testing
1. Run multiple tool commands in one prompt
2. Check that each permission request shows up
3. Refresh the page and verify thinking tags are still collapsible
4. Check `permissions` table in SQLite to verify logging

## Files Modified
1. `server/app/static/js/ui-components.js` - Hide permission cards
2. `server/app/static/js/stream-handler.js` - Separate messages per turn
3. `server/app/database.py` - Add permissions table and log function
4. `server/app/main.py` - Log permission decisions
5. `server/app/static/js/session-manager.js` - Parse thinking tags on reload
