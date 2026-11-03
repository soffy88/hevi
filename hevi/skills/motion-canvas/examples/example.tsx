import {Circle, Code, LezerHighlighter, Txt, makeScene2D} from '@motion-canvas/2d';
import {all, createRef, waitFor} from '@motion-canvas/core';
import {parser} from '@lezer/javascript';

Code.defaultHighlighter = new LezerHighlighter(parser);

export default makeScene2D(function* (view) {
  view.fill('#101418');

  const code = createRef<Code>();
  const circle = createRef<Circle>();
  const caption = createRef<Txt>();

  view.add(
    <>
      <Code
        ref={code}
        fontFamily={'monospace'}
        fontSize={40}
        offset={[-1, -1]}
        position={[-860, -300]}
        code={`// grow the circle`}
      />
      <Circle ref={circle} size={160} fill={'#68abdf'} position={[430, 40]} />
      <Txt
        ref={caption}
        fontFamily={'monospace'}
        fontSize={44}
        fill={'#d7dde6'}
        position={[430, 300]}
        opacity={0}
      >
        radius: 80
      </Txt>
    </>,
  );

  yield* waitFor(0.5);

  // "typing": tweening the code signal diffs old -> new code on screen
  yield* code().code(
    `const circle = new Circle({radius: 80});\ncircle.scale(2);\ncircle.fill('#e13238');`,
    1.8,
  );

  yield* waitFor(0.3);

  // the shape obeys the code
  yield* all(
    circle().scale(2, 1.2),
    circle().fill('#e13238', 1.2),
    caption().opacity(1, 0.6),
  );

  yield* waitFor(0.4);

  yield* all(
    code().code(
      `const circle = new Circle({radius: 80});\ncircle.scale(2);\ncircle.fill('#e13238');\ncircle.position.x += 260;`,
      1.2,
    ),
    circle().position.x(690, 1.2),
  );

  yield* waitFor(0.6);
});
