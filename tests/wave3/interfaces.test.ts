/**
 * W3.1: Execution Interfaces Tests
 */
import { describe, test, expect } from "bun:test";
import type { IDispatcher, ICompletionHandler, IProcessWatcher, INotifier } from "../../src/execution/interfaces.js";

describe("W3.1: Execution Interfaces", () => {
  test("IDispatcher has all methods", () => {
    const check = (d: IDispatcher) => {
      d.dispatch; d.cancel; d.isRunning; d.sessionIdToUuid; d.getResultFile; d.getStderrFile;
    };
    expect(typeof check).toBe("function");
  });

  test("ICompletionHandler has all methods", () => {
    const check = (c: ICompletionHandler) => {
      c.parseResultFile; c.handleCompletion; c.main;
    };
    expect(typeof check).toBe("function");
  });

  test("IProcessWatcher has all methods", () => {
    const check = (w: IProcessWatcher) => {
      w.start; w.stop; w.checkOnce;
    };
    expect(typeof check).toBe("function");
  });

  test("INotifier has all methods", () => {
    const check = (n: INotifier) => {
      n.formatMessage; n.notify; n.retryFailed;
    };
    expect(typeof check).toBe("function");
  });
});
