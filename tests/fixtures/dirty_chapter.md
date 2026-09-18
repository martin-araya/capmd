Capítulo 3: Ownership


La regla de ownership es simple: cada valor tiene un único dueño. Cuando el dueño
sale del scope, el valor se libera automáticamente. Esto resuelve los problemas de
doble liberación que aparecen en otros sistemas de gestión de memoria.


Para entenderlo mejor, consideremos el siguiente ejemplo en pseudo-código. El
concepto de “move” (movimiento) es central: cuando asignamos un valor a otra
variable, en realidad lo movemos, no lo copiamos. Esto evita copias innecesarias
y hace que el código sea más eﬁciente.






— 47 —

A diferencia de otros lenguajes, Rust garantiza estas propiedades en tiempo de
compilación, sin necesidad de un garbage collector. El compilador analiza el
“borrow checker” para asegurar que no hay referencias colgantes.


Resumen

En este capítulo vimos cómo Rust gestiona la memoria sin un GC. Los conceptos
clave son ownership, borrowing y lifetimes. El próximo capítulo explorará los
traits y cómo permiten polimorﬁsmo estático.
