// Minimal local type shims so the editor/CI linter can typecheck this repo
// even before `node_modules` are installed.
//
// At runtime/build time, the Docker image installs real dependencies, so these
// shims should be considered a fallback for development environments where
// package installation hasn't happened yet.

declare module "vitest" {
    export const describe: any;
    export const it: any;
    export const expect: any;
}

declare module "vitest/config" {
    export function defineConfig(config: any): any;
}

declare module "@vitejs/plugin-react" {
    const react: any;
    export default react;
}

declare module "@testing-library/react" {
    export const render: any;
    export const screen: any;
}

declare module "@testing-library/jest-dom/vitest" { }

// Minimal React hook typings for editor typecheck when node_modules isn't installed.
declare module "react" {
    export type ReactNode = any;
    export function useEffect(effect: any, deps?: any[]): void;
    export function useState<T = any>(initial?: T): [T, (v: any) => void];
    export function useRef<T = any>(initial?: T): { current: T };
    export function useMemo<T = any>(factory: () => T, deps: any[]): T;
}

declare global {
    // Allow JSX in TS files without relying on React's type declarations.
    namespace JSX {
        interface IntrinsicElements {
            [elemName: string]: any;
        }
    }

    // Allow access to process.env in Next.js pages without Node typings present.
    const process: {
        env: Record<string, string | undefined>;
    };
}

export { };


