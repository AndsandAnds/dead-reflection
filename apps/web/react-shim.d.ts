// Minimal shim for editor/linter environments where node_modules aren't installed.
// This file intentionally has no imports/exports so the module declaration is global.

declare module "react" {
    export type ReactNode = any;

    export function useEffect(effect: () => void | (() => void), deps?: any[]): void;

    export function useRef<T>(initialValue: T): { current: T };
    export function useRef<T>(initialValue: T | null): { current: T | null };

    export function useState<S>(
        initialState: S | (() => S),
    ): [S, (value: S | ((prev: S) => S)) => void];
}


