/**
 * Test environment setup.
 *
 * Next's router and Link have no meaning in jsdom, so both are replaced with
 * the smallest thing that behaves correctly: recorded navigation calls and a
 * plain anchor. Everything else under test is the real component.
 */

import "@testing-library/jest-dom/vitest";

import { createElement, type ReactNode } from "react";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  routerMock.push.mockClear();
  routerMock.replace.mockClear();
  window.sessionStorage.clear();
});

export const routerMock = {
  push: vi.fn(),
  replace: vi.fn(),
};

vi.mock("next/navigation", () => ({
  useRouter: () => routerMock,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
  }) => createElement("a", { href, ...rest }, children),
}));
